"""Bot handlers for Phase 1-3.

Contains /start, /ajuda, /adicionar, /fixos, /orcamento, /receber and natural message handling.
"""

import re
import os
import logging
from datetime import datetime
from typing import Optional, List
import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, MessageHandler, filters, CommandHandler
from supabase import create_client

from pilas_personal_finance.services.transaction_service import TransactionService
from pilas_personal_finance.services.benefit_service import calculate_benefit_by_day, calculate_irrrf
from pilas_personal_finance.services.recurring_expense_service import (
    create_recurring_expense,
    get_user_recurring_expenses,
    mark_occurrence_as_paid,
    calculate_budget_projection,
)
from pilas_personal_finance.repositories import AppUsersRepo

logger = logging.getLogger(__name__)

TZ_SAO_PAULO = pytz.timezone("America/Sao_Paulo")


def get_supabase():
    """Create and return a fresh Supabase client from environment variables."""
    from supabase import create_client as _cc
    return _cc(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))


# --- Allowlist ---
# Load from .env in production; for now allow all in development,
# or read from environment variables ALLOWED_USER_IDS and ALLOWED_USERNAMES
def load_allowed_user_ids() -> set:
    """Load allowed Telegram user IDs from environment."""
    ids_str = os.getenv("ALLOWED_USER_IDS", "")
    return {int(x.strip()) for x in ids_str.split(",") if x.strip()}

def load_allowed_usernames() -> set:
    """Load allowed Telegram usernames from environment (without @)."""
    usernames_str = os.getenv("ALLOWED_USERNAMES", "")
    return {x.strip().lower() for x in usernames_str.split(",") if x.strip()}

ALLOWED_USER_IDS = load_allowed_user_ids()
ALLOWED_USERNAMES = load_allowed_usernames()


def is_authorized(telegram_user_id: int, username: Optional[str] = None) -> bool:
    """Check if user is in the allowlist.

    Checks both numeric user ID and username.
    Empty allowlists deny everyone (safe default per spec).
    """
    if telegram_user_id in ALLOWED_USER_IDS:
        return True
    if username and username.lower() in ALLOWED_USERNAMES:
        return True
    logger.warning(
        "ACCESS DENIED: user_id=%s username=%s", telegram_user_id, username
    )
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

    # Dispatch subcommands: "/fixos adicionar ..." or "/fixos pagos"
    args = context.args or []
    if args and args[0].lower() in ("adicionar", "add"):
        await fixos_adicionar_command(update, context)
        return
    if args and args[0].lower() in ("pagos", "paid"):
        await fixos_pagos_command(update, context)
        return

    supabase = get_supabase()

    # Get user's recurring expenses
    recurring = get_user_recurring_expenses(supabase, telegram_user_id)

    if not recurring:
        await update.message.reply_text(
            "Não há despesas recorrentes cadastradas.\n"
            "Use /fixos adicionar para cadastrar uma nova. Ex: /fixos adicionar Aluguel 1500 mensal 5",
            reply_markup=get_main_keyboard()
        )
        return

    # Format the list
    text = "📋 Despesas Recorrentes Cadastradas\n\n"
    for i, exp in enumerate(recurring, 1):
        text += f"{i}. {exp['description']} - R$ {float(exp['expected_amount']):.2f} ({exp.get('frequency', 'mensal')}) - {exp.get('scope', 'PERSONAL')}\n"

    text += "\nUse /fixos adicionar para cadastrar uma nova recorrência.\nUse /pagar para marcar o pagamento."

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


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
        text = update.message.text.replace("/fixos_adicionar", "").replace("/fixos adicionar", "").strip()
        if text:
            # Format expected: "descricao valor frequencia [dia]" or natural msg
            # Ex: "/fixos adicionar Aluguel 1500 mensal 5"
            supabase = get_supabase()

            m = re.match(
                r"^(?P<desc>.+?)\s+(?P<value>\d+[.,]?\d*)"
                r"(?:\s+no\s+(?P<instr>.+?))?"
                r"(?:\s+(?P<freq>mensal|semanal|anual))?"
                r"(?:\s+(?P<day>\d{1,2}))?$",
                text.strip(),
                re.IGNORECASE,
            )
            if not m:
                await update.message.reply_text(
                    "Formato: `/fixos adicionar Descrição valor [no cartão/boleto] [mensal|semanal|anual] [dia]`\n"
                    "Ex: `/fixos adicionar Netflix 39,90 no Inter mensal 5`\n"
                    "Ex: `/fixos adicionar Aluguel 1500 boleto mensal 5`",
                    parse_mode="Markdown",
                )
                return

            description = m.group("desc").strip()
            value = float(m.group("value").replace(",", "."))
            instr_name = m.group("instr")
            freq = (m.group("freq") or "mensal").lower()
            day = int(m.group("day")) if m.group("day") else None

            # Resolve authenticated user + payment instrument
            user_repo = AppUsersRepo(supabase)
            user = user_repo.find_by_telegram_id(telegram_user_id)
            if not user:
                await update.message.reply_text("Usuário não encontrado. Use /start primeiro.")
                return

            instrument_id = None
            instrument_label = "boleto/indefinido"
            if instr_name and instr_name.lower() != "boleto":
                from pilas_personal_finance.repositories import PaymentInstrumentsRepo
                instr_repo = PaymentInstrumentsRepo(supabase)
                candidates = (instr_repo.find_by_owner(user["id"]) +
                              instr_repo.find_shared())
                instr = next(
                    (i for i in candidates
                     if i.get("name", "").lower() == instr_name.lower().strip()),
                    None,
                )
                if instr:
                    instrument_id = instr["id"]
                    instrument_label = instr["name"]
                else:
                    await update.message.reply_text(
                        f"⚠️ Instrumento \"{instr_name}\" não encontrado - cadastro sem instrumento.\n"
                        "Instrumentos existentes: " + ", ".join(
                            i["name"] for i in candidates[:8]))

            try:
                rec = create_recurring_expense(
                    supabase, user["id"], description, None,
                    value, freq, due_day=day,
                    payment_instrument_id=instrument_id,
                )
                await update.message.reply_text(
                    f"✅ Despesa fixa cadastrada: {rec['description']} - "
                    f"R$ {float(rec['expected_amount']):.2f} ({rec['frequency']}"
                    + (f", vence dia {day}" if day else "")
                    + f", origem: {instrument_label})"
                )
            except Exception as e:
                await update.message.reply_text(f"Erro ao cadastrar: {str(e)[:200]}")
        else:
            await update.message.reply_text(
                "Use: `/fixos adicionar Descrição valor [mensal|semanal|anual] [dia]`\n"
                "Ex: `/fixos adicionar Aluguel 1500 mensal 5`",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            "Use: `/fixos adicionar Descrição valor [mensal|semanal|anual] [dia]`\n"
            "Ex: `/fixos adicionar Aluguel 1500 mensal 5`",
            parse_mode="Markdown",
        )


async def fixos_pagos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fixos pagos command."""
    user = update.effective_user
    telegram_user_id = user.id
    username = user.username

    if not is_authorized(telegram_user_id, username):
        await update.message.reply_text("Acesso negado.")
        return


    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(telegram_user_id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    from datetime import datetime
    import pytz
    tz = pytz.timezone("America/Sao_Paulo")
    current_month = datetime.now(tz).strftime("%Y-%m")

    from pilas_personal_finance.services.recurring_expense_service import (
        ensure_month_occurrences, get_upcoming_occurrences,
    )
    ensure_month_occurrences(supabase, app_user["id"], current_month)
    occurrences = get_upcoming_occurrences(supabase, app_user["id"], current_month)

    parents = {r["id"]: r for r in get_user_recurring_expenses(
        supabase, app_user["id"], active_only=False)}

    paid, pending = [], []
    for o in occurrences:
        rec = parents.get(o.get("recurring_expense_id"), {})
        item = {
            "description": rec.get("description", "?"),
            "amount": o.get("actual_amount") or o.get("expected_amount"),
            "frequency": rec.get("frequency", "mensal"),
            "due_day": rec.get("due_day"),
            "status": o.get("status"),
        }
        (paid if o.get("status") == "PAID" else pending).append(item)

    text = f"💰 Despesas fixas de {current_month}\n\n"

    if paid:
        text += "✅ Pagas:\n"
        for r in paid:
            text += f"• {r['description']} - R$ {float(r['amount']):.2f}\n"
        text += "\n"
    else:
        text += "Nenhuma despesa fixa paga este mês.\n\n"

    if pending:
        text += "⏳ Pendentes:\n"
        for r in pending:
            day = f", vence dia {r['due_day']}" if r.get('due_day') else ""
            text += f"• {r['description']} - R$ {float(r['amount']):.2f} ({r['frequency']}{day})\n"
        text += "\n"
    else:
        text += "Nenhuma despesa fixa pendente.\n\n"

    text += "Use /pagar para marcar manualmente, ou registre o gasto naturalmente (ex: 'Netflix 39,90 no Inter') - detecto e fecho sozinho."

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


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
    """Handle /receber command - register or list receivables ("me deve").

    /receber                          -> lista
    /receber Nome descricao... valor  -> cria
    """
    user = update.effective_user
    telegram_user_id = user.id

    if not is_authorized(telegram_user_id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(telegram_user_id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    text_arg = update.message.text.replace("/receber", "").strip() if update.message and update.message.text else ""
    if not text_arg:
        await list_receivables_command(update, context)
        return

    # Parse: "<debtor> <description words...> <value>" (value = last token)
    parts = text_arg.split()
    if len(parts) < 3:
        await update.message.reply_text(
            "Formato: `/receber Nome descrição valor`\nEx: `/receber João jantar de aniversário 80`",
            parse_mode="Markdown",
        )
        return

    try:
        value = float(parts[-1].replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Valor inválido. Use: `/receber Nome descrição valor`",
            parse_mode="Markdown",
        )
        return

    debtor = parts[0]
    description = " ".join(parts[1:-1])

    result = supabase.from_("receivables").insert({
        "creditor_user_id": app_user["id"],
        "debtor_name": debtor,
        "description": description,
        "original_amount": value,
        "received_amount": 0,
        "created_date": datetime.now(TZ_SAO_PAULO).strftime("%Y-%m-%d"),
        "scope": "PERSONAL",
        "status": "OPEN",
    }).execute()

    if result.data:
        await update.message.reply_text(
            f"✅ Conta a receber cadastrada:\nDevedor: {debtor}\n"
            f"Descrição: {description}\nValor: R$ {value:.2f} - Status: OPEN",
            reply_markup=get_main_keyboard(),
        )
    else:
        await update.message.reply_text("Erro ao cadastrar. Tente novamente.")


async def _user_receivables(supabase, user_uuid):
    """Open/partial receivables of a user, most recent first."""
    result = supabase.from_("receivables").select("*").eq(
        "creditor_user_id", user_uuid
    ).in_("status", ["OPEN", "PARTIAL"]).order(
        "created_date", desc=True
    ).execute()
    return result.data or []


async def list_receivables_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List current receivables (me deve)."""
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(user.id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    receivables = await _user_receivables(supabase, app_user["id"])

    if not receivables:
        await update.message.reply_text(
            "Não há contas a receber em aberto.\n"
            "Para registrar: `/receber Nome descrição valor`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    text = "📋 Contas a Receber (Me Deve)\n\n"
    total = 0.0
    for i, r in enumerate(receivables, 1):
        remaining = float(r["original_amount"]) - float(r["received_amount"])
        total += remaining
        text += (f"{i}. {r['debtor_name']} - {r.get('description', '')[:30]}\n"
                 f"   Restante: R$ {remaining:.2f} de R$ {float(r['original_amount']):.2f}"
                 f" ({r['status']})\n\n")
    text += f"Soma em aberto: R$ {total:.2f} (incerto)\n"
    text += "Registrar recebimento: /registrar <número> <valor>"

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


async def registrar_recebimento_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a partial or full payment: /registrar <n> <valor>."""
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(user.id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Formato: `/registrar <número da lista> <valor>`\nEx: `/registrar 2 30`",
            parse_mode="Markdown",
        )
        return

    try:
        index = int(context.args[0])
        amount = float(context.args[1].replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Argumentos inválidos. Use: `/registrar <número> <valor>`",
            parse_mode="Markdown",
        )
        return

    receivables = await _user_receivables(supabase, app_user["id"])
    if not receivables or index < 1 or index > len(receivables):
        await update.message.reply_text(
            "Número não encontrado na lista. Use /recebimentos para ver a lista.")
        return

    rec = receivables[index - 1]
    new_received = float(rec["received_amount"]) + amount
    original = float(rec["original_amount"])
    new_status = "PAID" if new_received >= original - 0.005 else "PARTIAL"

    supabase.from_("receivables").update({
        "received_amount": round(new_received, 2),
        "status": new_status,
    }).eq("id", rec["id"]).execute()

    # Receiving money = INCOME (deterministic, linked to the receivable)
    tx = supabase.from_("transactions").insert({
        "user_id": app_user["id"],
        "category_id": None,
        "type": "INCOME",
        "scope": rec.get("scope", "PERSONAL"),
        "amount": amount,
        "description": f"Recebimento de {rec['debtor_name']}: {rec.get('description', '')}",
        "transaction_date": datetime.now(TZ_SAO_PAULO).strftime("%Y-%m-%d"),
        "source": "MANUAL",
        "external_reference": rec["id"],
        "telegram_update_id": update.message.message_id,
    }).execute()

    await update.message.reply_text(
        f"✅ Recebimento registrado: R$ {amount:.2f} de {rec['debtor_name']}\n"
        f"Restante: R$ {max(original - new_received, 0):.2f} ({new_status})",
        reply_markup=get_main_keyboard(),
    )


# --- Budget Command (/orcamento) ---

async def cartoes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List payment instruments (cards, pix, cash, voucher)."""
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(user.id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    from pilas_personal_finance.repositories import PaymentInstrumentsRepo
    repo = PaymentInstrumentsRepo(supabase)
    try:
        instruments = repo.find_by_owner(app_user["id"]) + repo.find_shared()
    except Exception as e:
        logger.error(f"/cartoes failed: {e}")
        instruments = []

    if not instruments:
        await update.message.reply_text(
            "Nenhum instrumento cadastrado.\n"
            "Mensagens como 'Almoço 42,50 no Nubank crédito' criam instrumentos automaticamente.",
            reply_markup=get_main_keyboard(),
        )
        return

    text = "💳 Instrumentos de Pagamento\n\n"
    for inst in instruments:
        typ = inst.get("instrument_type", "OTHER")
        text += f"• {inst['name']} ({typ})\n"
    text += "\nMencione o instrumento na mensagem da despesa, ex: 'Mercado 100 no Pix Nubank'."

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


async def categorias_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List valid categories (hardcoded authoritative list)."""
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    from pilas_personal_finance.services.transaction_service import (
        HARDCODED_CATEGORIES_EXPENSE, HARDCODED_CATEGORIES_INCOME,
    )

    text = "🏷 Categorias de despesa:\n\n"
    text += ", ".join(HARDCODED_CATEGORIES_EXPENSE)
    text += "\n\n🏷 Categorias de receita:\n\n"
    text += ", ".join(HARDCODED_CATEGORIES_INCOME)
    text += "\n\nA IA escolhe apenas entre estas categorias. Padrão sem match: Outros."

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


async def relatorio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder: HTML report is Phase 5 (per spec)."""
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return
    await update.message.reply_text(
        "📄 O relatório HTML chega na Fase 5 (Jinja2 + análise IA).\n"
        "Por enquanto use /orcamento (números) e /fixos (pendências).",
        reply_markup=get_main_keyboard(),
    )


async def orcamento_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /orcamento command.

    Show budget projection for the current month with three perspectives:
    - Disponível agora (confirmed)
    - Disponível projetado (expected revenues + commitments)
    - Cenário incluindo recebíveis (identified as uncertain)
    """
    user = update.effective_user
    if not is_authorized(user.id, user.username):
        await update.message.reply_text("Acesso negado.")
        return

    supabase = get_supabase()
    app_user = AppUsersRepo(supabase).find_by_telegram_id(user.id)
    if not app_user:
        await update.message.reply_text("Usuário não registrado. Use /start primeiro.")
        return

    from datetime import datetime
    import pytz
    tz = pytz.timezone("America/Sao_Paulo")
    current_month = datetime.now(tz).strftime("%Y-%m")

    try:
        projection = calculate_budget_projection(supabase, app_user["id"], current_month)
    except Exception as e:
        logger.error(f"/orcamento failed: {e}")
        await update.message.reply_text("Erro ao calcular o orçamento. Tente novamente.")
        return

    available_now = projection["available_now"]
    available_projected = projection["available_projected"]
    receiveables_pending = projection["receiveables_pending"]
    total_incomes = _income_line(supabase, app_user["id"], current_month)

    text = f"📊 Orçamento de {current_month}\n\n"
    text += f"🟢 Disponível agora: R$ {available_now:.2f}\n"
    text += f"   (valores efetivamente recebidos e gastos confirmados)\n\n"
    text += f"🟡 Disponível projetado até o fim do mês: R$ {available_projected:.2f}\n"
    text += f"   (abate custos fixos ainda pendentes)\n\n"
    text += f"🔵 Cenário incluindo recebíveis: R$ {available_projected + receiveables_pending:.2f}\n"
    text += f"   (incerto - recebíveis NÃO são dinheiro confirmado)\n\n"
    text += "📊 Resumo:\n"
    text += f"   • Total de receitas recebidas: R$ {total_incomes:.2f}\n"
    text += f"   • Total de despesas realizadas: R$ {projection['total_expenses_realized']:.2f}\n"
    text += f"   • Custos fixos pendentes: R$ {projection['total_fixed_pending']:.2f}\n\n"
    if receiveables_pending > 0:
        text += f"⚠️ A receber (não confirmado): R$ {receiveables_pending:.2f}\n"
        text += "   (não somado ao disponível confirmado)\n"

    await update.message.reply_text(text, reply_markup=get_main_keyboard())


def _income_line(supabase, user_uuid, month):
    """Total received income for the month (confirmed INCOME transactions)."""
    try:
        rows = supabase.from_("transactions").select("amount, type").eq(
            "user_id", user_uuid).eq("type", "INCOME").gte(
            "transaction_date", f"{month}-01").execute()
        return round(sum(float(r["amount"]) for r in (rows.data or [])), 2)
    except Exception as e:
        logger.warning(f"_income_line failed: {e}")
        return 0


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

    supabase = get_supabase()
    service = TransactionService(supabase)

    # Income messages ("Recebi 6500 de salário") get a dedicated path
    if service.is_income_message(message_text):
        tx = service.register_income_message(
            telegram_user_id, message_text, update.message.message_id
        )
        if tx:
            await update.message.reply_text(
                f"💰 Entrada registrada: R$ {tx['amount']:.2f} - {tx['description']}"
            )
        else:
            await update.message.reply_text(
                "Não consegui entender essa entrada. Use: `Recebi 6500 de salário`",
                parse_mode="Markdown",
            )
        return

    tx = service.register_message(telegram_user_id, message_text, update.message.message_id)

    if tx:
        # Fetch related names for a friendly confirmation
        cat_name = ""
        if tx.get("category_id"):
            cat_r = supabase.from_("categories").select("name").eq("id", tx["category_id"]).execute()
            if cat_r.data:
                cat_name = cat_r.data[0]["name"]
        inst_name = ""
        if tx.get("payment_instrument_id"):
            inst_r = supabase.from_("payment_instruments").select("name").eq(
                "id", tx["payment_instrument_id"]).execute()
            if inst_r.data:
                inst_name = inst_r.data[0]["name"]
        reply = f"Registrado: R$ {tx['amount']:.2f} - {tx['description']}"
        if inst_name:
            reply += f" ({inst_name})"
        if cat_name:
            reply += f" - Categoria: {cat_name}"

        # Recurring auto-match feedback
        from pilas_personal_finance.services.recurring_expense_service import find_pending_occurrence
        occ = find_pending_occurrence(
            supabase, tx['user_id'], tx.get('description', ''), float(tx['amount'])
        )
        if occ:
            reply += "\n✅ Despesa fixa: ocorrência marcada como paga."
        await update.message.reply_text(reply)
    else:
        # Ask for clarification
        await update.message.reply_text(
            "Não consegui entender esse lançamento. Use o formato:\n"
            "- `Descrição valor no instrumento tipo`\n"
            "Ex: `Almoço 42,50 no Nubank crédito`\n\n"
            "Se o instrumento não for reconhecido, perguntarei para confirmar.",
            parse_mode="Markdown"
        )