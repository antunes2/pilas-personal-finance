"""Bot handlers for Phase 1-3.

Contains /start, /ajuda, /adicionar, /fixos, /orcamento, /receber and natural message handling.
"""

import re
from datetime import datetime
from typing import Optional, List
import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, MessageHandler, filters, CommandHandler

from pilas_personal_finance.services.transaction_service import TransactionService
from pilas_personal_finance.services.benefit_service import calculate_benefit_by_day, calculate_irrrf
from pilas_personal_finance.services.recurring_expense_service import (
    create_recurring_expense,
    get_user_recurring_expenses,
    mark_occurrence_as_paid,
    calculate_budget_projection,
)
from pilas_personal_finance.repositories import AppUsersRepo


# --- Allowlist ---
# Load from .env in production; for now allow all in development,
# or read from environment variables ALLOWED_USER_IDS and ALLOWED_USERNAMES
def load_allowed_user_ids() -> set:
    """Load allowed Telegram user IDs from environment."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    ids_str = os.getenv("ALLOWED_USER_IDS", "")
    if ids_str:
        return {int(x.strip()) for x in ids_str.split(",") if x.strip()}
    # In development, allow all users for testing
    # In production, this should be set explicitly
    return set()

def load_allowed_usernames() -> set:
    """Load allowed Telegram usernames from environment (without @)."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    usernames_str = os.getenv("ALLOWED_USERNAMES", "")
    if usernames_str:
        return {x.strip().lower() for x in usernames_str.split(",") if x.strip()}
    return set()

ALLOWED_USER_IDS = load_allowed_user_ids()
ALLOWED_USERNAMES = load_allowed_usernames()


def is_authorized(telegram_user_id: int, username: Optional[str] = None) -> bool:
    """Check if user is in the allowlist.
    
    Checks both numeric user ID and username.
    username should be the raw username string (without @) or None.
    """
    if telegram_user_id in ALLOWED_USER_IDS:
        return True
    if username and username.lower() in ALLOWED_USERNAMES:
        return True
    return False


# --- Keyboards ---

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard with common commands."""
    buttons = [
        [KeyboardButton("/orcamento"), KeyboardButton("/relatorio")],
        [KeyboardButton("/fixos"), KeyboardButton("/receber")],
        [KeyboardButton("/cartoes"), KeyboardButton("/categorias")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_yes_no_keyboard() -> ReplyKeyboardMarkup:
    """Yes/No confirmation keyboard."""
    buttons = [
        [KeyboardButton("Sim"), KeyboardButton("Não")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_fixed_expenses_keyboard(expenses: list) -> ReplyKeyboardMarkup:
    """Keyboard with fixed expense options."""
    if not expenses:
        buttons = [[KeyboardButton("Nenhuma recorrência cadastrada")]]
    else:
        buttons = []
        row = []
        for i, exp in enumerate(expenses):
            row.append(KeyboardButton(exp["description"]))
            if len(row) == 3 or i == len(expenses) - 1:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_payment_keyboard(instruments: list) -> ReplyKeyboardMarkup:
    """Keyboard with payment instrument buttons."""
    if not instruments:
        buttons = [[KeyboardButton("Outros")]]
    else:
        buttons = [[KeyboardButton(inst["name"]) for inst in instruments[i:i+3]] 
                   for i in range(0, len(instruments), 3)]
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    """Confirmation keyboard (Sim/Não)."""
    return get_yes_no_keyboard()


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command.

    Identify user, check allowlist, create user if needed.
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username  # May be None if user has no username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text(
            "Acesso negado. Este bot é restrito a dois usuários autorizados."
        )
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)

    # Find or create user
    existing = service.users_repo.find_by_telegram_id(telegram_user_id)
    if not existing:
        user_data = service.users_repo.create(telegram_user_id, display_name=user.full_name)
        await update.message.reply_text(
            f"Bem-vindo! {user_data['display_name']}, seu cadastro foi criado."
        )
    else:
        await update.message.reply_text(
            f"Olá {existing['display_name']}! Tudo bem? Use /ajuda para exemplos."
        )


async def ajuda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ajuda command.

    Show examples of natural language messages.
    """
    help_text = (
        "Comandos disponíveis:\n\n"
        "/start - Iniciar e identificar usuário\n"
        "/ajuda - Ajuda e exemplos\n"
        "/adicionar - Registrar receita ou despesa\n"
        "/fixos - Listar e administrar despesas recorrentes\n"
        "/fixos adicionar - Cadastrar uma recorrência\n"
        "/fixos pagos - Listar despesas recorrentes pagas e pendentes\n"
        "/pagar - Marcar ocorrência como paga e registrar pagamento\n"
        "/receber - Registrar/consultar valores a receber\n"
        "/orcamento - Disponível agora e projetado até o fim do mês\n"
        "/relatorio - Gerar relatório HTML\n"
        "/categorias - Listar categorias válidas\n"
        "/cartoes - Listar instrumentos de pagamento\n"
        "/resumo - Resumo do período\n"
        "\n"
        "Mensagens naturais também são aceitas sem comandos:\n"
        "- `Almoço 42,50 no Nubank crédito`\n"
        "- `Salário 5000`\n"
        "- `Uber 18,90 no Inter débito`\n"
        "- `VR 38,00 no vale refeição`\n"
        "\n"
        "Use /menu para ver o menu interativo."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def adicionar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /adicionar command.

    Manually register a transaction with natural language.
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    # Check if message has text after /adicionar
    if update.message and update.message.text:
        text = update.message.text.replace("/adicionar", "").strip()
        if text:
            # Try to parse as natural language
            from main import get_supabase
            supabase = get_supabase()
            service = TransactionService(supabase)
            tx = service.register_message(telegram_user_id, text, update.message.message_id)
            if tx:
                await update.message.reply_text(
                    f"Registrado: R$ {tx['amount']:.2f} - {tx['description']} "
                    f"({tx['payment_instrument']['name']}) - Categoria: {tx['category']['name']}"
                )
            else:
                await update.message.reply_text(
                    "Não consegui entender a mensagem. Use o formato:\n"
                    "- `Almoço 42,50 no Nubank crédito`"
                )
        else:
            await update.message.reply_text(
                "Uso: `/adicionar` followed by a natural language message,\n"
                "ex: `/adicionar Almoço 42,50 no Nubank crédito`"
            )
    else:
        await update.message.reply_text(
            "Uso: `/adicionar` followed by a natural language message,\n"
            "ex: `/adicionar Almoço 42,50 no Nubank crédito`"
        )


# --- Fixed Expenses Commands (/fixos) ---

async def fixos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fixos command.

    List fixed expenses and provide options.
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)

    # Get user's recurring expenses
    recurring = get_user_recurring_expenses(supabase, telegram_user_id)
    
    if not recurring:
        await update.message.reply_text(
            "Não há despesas recorrentes cadastradas.\n"
            "Use `/fixos adicionar` para cadastrar uma nova.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Format the list
    text = "📋 **Despesas Recorrentes Cadastradas**\n\n"
    for i, exp in enumerate(recurring, 1):
        text += f"{i}. {exp['description']} - R$ {exp['expected_amount']:.2f} ({{exp['frequency']}}) - {exp['scope']}\n"
    
    text += "\nUse /fixos adicionar para cadastrar uma nova recorrência."
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())


async def fixos_adicionar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fixos adicionar command.
    
    Register a new recurring expense with prompts.
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    # Check if text after command
    if update.message and update.message.text:
        text = update.message.text.replace("/fixos adicionar", "").strip()
        if text:
            # Parse the text to extract recurring expense details
            # Format expected: "descricao valor frequencia dia"
            # ou mensagem natural que será processada
            
            from main import get_supabase
            supabase = get_supabase()
            service = TransactionService(supabase)
            
            # Try to parse as a natural language recurring expense
            # For now, we'll ask for structured data
            await update.message.reply_text(
                "Para cadastrar uma despesa recorrente, forneça os detalhes:\n\n"
                "1. Descrição (ex: 'Aluguel', 'Internet', 'Academia')\n"
                "2. Valor esperado (ex: '1500')\n"
                "3. Frequência (mensal, semanal, anual)\n"
                "4. Dia de vencimento (opcional, 1-31)\n\n"
                "Exemplo: `Aluguel 1500 mensal 5`\n\n"
                "Ou use o formato natural e eu tentarei processar.",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "Use `/fixos adicionar` followed by the details,\n"
                "ex: `/fixos adicionar Aluguel 1500 mensal 5`"
            )
    else:
        await update.message.reply_text(
            "Use `/fixos adicionar` followed by the details,\n"
            "ex: `/fixos adicionar Aluguel 1500 mensal 5`"
        )


async def fixos_pagos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fixos pagos command."""
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    recurring = get_user_recurring_expenses(supabase, telegram_user_id)
    
    # Separate paid and pending
    paid = [r for r in recurring if r.get('status') == 'PAID' or r.get('is_active') == False]
    pending = [r for r in recurring if r.get('status') != 'PAID' and r.get('is_active')]
    
    text = "💰 **Despesas Recorrentes**\n\n"
    
    if paid:
        text += "✅ **Pagas:**\n"
        for r in paid:
            text += f"• {r['description']} - R$ {r['expected_amount']:.2f} ({r['frequency']})\n"
        text += "\n"
    else:
        text += "Não há despesas recorrentes marcadas como pagas.\n\n"
    
    if pending:
        text += "⏳ **Pendentes:**\n"
        for r in pending:
            text += f"• {r['description']} - R$ {r['expected_amount']:.2f} ({r['frequency']}) - Vencimento: dia {r.get('due_day', 'non specified')}\n"
        text += "\n"
    else:
        text += "Não há despesas recorrentes pendentes.\n\n"
    
    text += "Use /pagar para marcar uma ocorrência como paga."
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())


async def pagar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pagar command.
    
    Mark a recurring expense occurrence as paid and register the payment.
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    # Get user's recurring expenses
    recurring = get_user_recurring_expenses(supabase, telegram_user_id)
    pending = [r for r in recurring if r.get('status') != 'PAID' and r.get('is_active')]
    
    if not pending:
        await update.message.reply_text(
            "Não há despesas recorrentes pendentes para pagar.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Show the pending ones
    text = "💳 **Qual despesa você pagou?**\n\n"
    for i, r in enumerate(pending, 1):
        text += f"{i}. {r['description']} - R$ {r['expected_amount']:.2f} ({r['frequency']})\n"
    
    text += "\nResponda com o número da despesa que pagou, ou use /pagar N."
    await update.message.reply_text(text, reply_markup=get_main_keyboard())


# --- Receivables Commands (/receber) ---

async def receber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /receber command.
    
    Register/receive values a receber (me deve).
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    # Check if text after command
    if update.message and update.message.text:
        text = update.message.text.replace("/receber", "").strip()
        if text:
            # Parse: "devedor descricao valor"
            # ou mensagem natural
            parts = text.split()
            if len(parts) >= 3:
                try:
                    debtor = parts[0]
                    # Value might be last part or second-to-last
                    value_str = parts[-1].replace(',', '.')
                    value = float(value_str)
                    description = " ".join(parts[1:-1])
                    
                    # Create receivable
                    result = supabase.from_("receivables").insert({
                        "creditor_user_id": telegram_user_id,
                        "debtor_name": debtor,
                        "description": description,
                        "original_amount": value,
                        "received_amount": 0,
                        "created_date": datetime.utcnow().isoformat(),
                        "scope": "PERSONAL",
                        "status": "OPEN",
                    }).execute()
                    
                    if result.data and len(result.data) > 0:
                        receivable = result.data[0]
                        await update.message.reply_text(
                            f"✅ Conta a receber cadastrada:\n"
                            f"Devedor: {receivable['debtor_name']}\n"
                            f"Descrição: {receivable['description']}\n"
                            f"Valor total: R$ {receivable['original_amount']:.2f}\n"
                            f"Status: OPEN\n\n"
                            f"Use `/receber {receivable['id']} {value}` para registrar recebimento.",
                            reply_markup=get_main_keyboard()
                        )
                    else:
                        await update.message.reply_text(
                            "Erro ao cadastrar conta a receber. Tente novamente.",
                            reply_markup=get_main_keyboard()
                        )
                except ValueError:
                    await update.message.reply_text(
                        "Formato inválido. Use: `/receber nome da pessoa descricao valor`\n"
                        "Ex: `/receber João jantar de aniversário 80`",
                        reply_markup=get_main_keyboard()
                    )
            else:
                await update.message.reply_text(
                    "Formato inválido. Use: `/receber nome descricao valor`\n"
                    "Ex: `/receber João jantar de aniversário 80`",
                    reply_markup=get_main_keyboard()
                )
        else:
            # List current receivables
            await list_receivables_command(update, context)
    else:
        # List current receivables
        await list_receivables_command(update, context)


async def list_receivables_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List current receivables (me deve)."""
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    # Query receivables
    result = supabase.from_("receivables").select("*").eq("creditor_user_id", telegram_user_id).execute()
    receivables = result.data or []
    
    if not receivables:
        await update.message.reply_text(
            "Não há contas a receber cadastradas.",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "📋 **Contas a Receber (Me Deve)**\n\n"
    for i, r in enumerate(receivables, 1):
        text += f"{i}. Devedor: {r.get('debtor_name', 'N/A')}\n"
        text += f"   Descrição: {r.get('description', 'N/A')[:30]}\n"
        text += f"   Valor total: R$ {r.get('original_amount', 0):.2f}\n"
        text += f"   Já recebido: R$ {r.get('received_amount', 0):.2f}\n"
        text += f"   Status: {r.get('status', 'OPEN')}\n"
        text += f"   Data: {r.get('created_date', 'N/A')[:10]}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())


async def registrar_recebimento_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a partial or full payment on a receivable."""
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    # Get args: receivable_id amount
    if context and context.args:
        args = context.args
        try:
            receivable_id = args[0]
            amount_str = args[1].replace(',', '.')
            amount = float(amount_str)
            
            # Update receivable
            supabase.from_("receivables").update({
                "received_amount": supabase.from_("receivables").select("received_amount").eq("id", receivable_id).single().get("received_amount", 0) + amount,
                "status": "PARTIAL" if supabase.from_("receivables").select("received_amount").eq("id", receivable_id).single().get("received_amount", 0) + amount < supabase.from_("receivables").select("original_amount").eq("id", receivable_id).single().get("original_amount", 0) else "PAID"
            }).eq("id", receivable_id).execute()
            
            # Create transaction for the payment
            # Get the receivable details
            receivable = supabase.from_("receivables").select("*").eq("id", receivable_id).single().execute()
            if receivable.data:
                receivable_data = receivable.data
                
                # Create transaction
                tx_result = supabase.from_("transactions").insert({
                    "user_id": telegram_user_id,
                    "category_id": None,
                    "payment_instrument_id": None,
                    "type": "EXPENSE",
                    "scope": "PERSONAL",
                    "amount": amount,
                    "description": f"Pagamento de conta a receber: {receivable_data.get('description', 'N/A')}",
                    "transaction_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "competence_month": datetime.utcnow().strftime("%Y-%m-%d"),
                    "source": "MANUAL",
                    "external_reference": receivable_data.get('id'),
                    "telegram_update_id": update.message.message_id,
                    "ai_category_confidence": None,
                }).execute()
                
                await update.message.reply_text(
                    f"✅ Pagamento registrado!\n"
                    f"Conta: {receivable_data.get('debtor_name')}\n"
                    f"Valor: R$ {amount:.2f}\n"
                    f"Status: {'Parcial' if supabase.from_('receivables').select('received_amount').eq('id', receivable_id).single().get('received_amount', 0) < receivable_data.get('original_amount', 0) else 'Total'}\n\n"
                    f"Total restante: R$ {receivable_data.get('original_amount', 0) - supabase.from_('receivables').select('received_amount').eq('id', receivable_id).single().get('received_amount', 0):.2f}",
                    reply_markup=get_main_keyboard()
                )
            else:
                await update.message.reply_text(
                    "Conta a receber não encontrada.",
                    reply_markup=get_main_keyboard()
                )
        except (ValueError, IndexError):
            await update.message.reply_text(
                "Formato inválido. Use: `/receber registrar ID_VALOR`\n"
                "Ex: `/receber registrar 1 50`",
                reply_markup=get_main_keyboard()
            )
    else:
        await update.message.reply_text(
            "Use `/receber registrar ID_VALOR` para registrar um pagamento.\n"
            "Ex: `/receber registrar 1 50`\n\n"
            "Ou use `/receber listar` para ver contas a receber.",
            reply_markup=get_main_keyboard()
        )


# --- Budget Command (/orcamento) ---

async def orcamento_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /orcamento command.
    
    Show budget projection for the current month with three perspectives:
    - Disponível agora (confirmed)
    - Disponível projetado (expected revenues + commitments)
    - Cenário incluindo recebíveis (identified as uncertain)
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)
    
    # Get current month
    from datetime import datetime
    import pytz
    tz = pytz.timezone("America/Sao_Paulo")
    current_month = datetime.now(tz).strftime("%Y-%m")
    
    # Calculate budget projection
    projection = calculate_budget_projection(supabase, telegram_user_id, current_month)
    
    # Get user's recurring expenses
    recurring = get_user_recurring_expenses(supabase, telegram_user_id)
    
    # Get recent transactions
    result = supabase.from_("transactions").select(
        "*", count="exact"
    ).eq("user_id", telegram_user_id).gte(
        "transaction_date", f"{current_month}-01"
    ).lte("transaction_date", f"{current_month}-31")
    result.execute()
    transactions = result.data or []
    
    # Categorize transactions
    expenses = [t for t in transactions if t.get("type") == "EXPENSE"]
    incomes = [t for t in transactions if t.get("type") == "INCOME"]
    
    # Calculate totals
    total_expenses = sum(t.get("amount", 0) for t in expenses)
    total_incomes = sum(t.get("amount", 0) for t in incomes)
    
    # Fixed costs pending (not paid)
    fixed_pending = sum(r.get("expected_amount", 0) for r in recurring if r.get('is_active') and r.get('status') != 'PAID')
    
    # Available NOW = income received - expenses realized
    # Based on confirmed values only (not expected/received)
    available_now = total_incomes - total_expenses
    if available_now < 0:
        available_now = 0
    
    # Available PROJECTED = available now + expected benefits - fixed pending
    # Includes expected revenues and future commitments, but NOT open receivables as confirmed money
    available_projected = available_now - fixed_pending + projection['available_projected'] - projection['available_now']
    
    # Receivables pending (shown separately, NOT added to confirmed values)
    receiveables_pending = projection.get('receiveables_pending', 0)
    
    # Build the message with three perspectives per spec
    text = f"📊 **Orçamento de {current_month}**\n\n"
    
    # Line 1: Disponível agora
    text += f"🟢 **Disponível agora:** R$ {available_now:.2f}\n"
    text += f"   * baseado em valores efetivamente recebidos e gastos confirmados\n\n"
    
    # Line 2: Disponível projetado
    text += f"🟡 **Disponível projetado até o fim do mês:** R$ {available_projected:.2f}\n"
    text += f"   * inclui receitas esperadas e compromissos futuros\n\n"
    
    # Line 3: Cenário incluindo recebíveis (opcional, identificado como incerto)
    text += f"🔵 **Cenário incluindo recebíveis:** R$ {available_projected + receiveables_pending:.2f}\n"
    text += f"   * identificado como incerto, NÃO somado ao disponível confirmado\n\n"
    
    # Summary section
    text += f"📊 **Resumo:**\n"
    text += f"   • Total de receitas recebidas: R$ {total_incomes:.2f}\n"
    text += f"   • Total de despesas realizadas: R$ {total_expenses:.2f}\n"
    text += f"   • Custos fixos pendentes: R$ {fixed_pending:.2f}\n"
    text += f"   • Livre para gastos: R$ {available_projected:.2f}\n\n"
    
    # Receivables note
    if receiveables_pending > 0:
        text += f"⚠️ **Contas a receber (pendentes):** R$ {receiveables_pending:.2f}\n"
        text += f"   *Não somado ao disponível confirmado* (identificado como incerto)\n\n"
    
    # Key recommendations
    text += f"💡 **Recomendações:**\n"
    text += f"   • Gastos livres: R$ {max(0, available_projected):.2f}\n"
    text += f"   • Cuidado ao considerar recebíveis como dinheiro disponível\n"
    text += f"   • Orçamento projetado considera compromissos futuros\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())


# --- Natural Message Handler ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages (not commands).

    Accepts natural language like:
    'Almoço 42,50 no Nubank crédito'
    """
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username
    message_text = update.message.text

    # Check if it's a command (starts with /)
    if message_text.startswith("/"):
        return

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return

    # Parse and register the transaction
    from main import get_supabase
    supabase = get_supabase()
    service = TransactionService(supabase)

    tx = service.register_message(telegram_user_id, message_text, update.message.message_id)

    if tx:
        await update.message.reply_text(
            f"Registrado: R$ {tx['amount']:.2f} - {tx['description']} "
            f"({tx['payment_instrument']['name']}) - Categoria: {tx['category']['name']}"
        )
    else:
        # Ask for clarification
        await update.message.reply_text(
            "Não consegui entender esse lançamento. Use o formato:\n"
            "- `Descrição valor no instrumento tipo`\n"
            "Ex: `Almoço 42,50 no Nubank crédito`\n\n"
            "Se o instrumento não for reconhecido, perguntarei para confirmar.",
            parse_mode="Markdown"
        )