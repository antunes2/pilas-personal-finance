"""Bot handlers for Phase 1.

Contains /start, /ajuda, /adicionar and natural message handling.
"""

import re
from datetime import datetime
from typing import Optional
import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, MessageHandler, filters, CommandHandler

from pilas_personal_finance.services.transaction_service import TransactionService
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
        "Como usar o bot:\n\n"
        "Registre transações escrevendo naturalmente:\n"
        "- `Almoço 42,50 no Nubank crédito`\n"
        "- `Uber 18,90 no Inter débito`\n"
        "- `Mercado 235,70 no Pix Nubank`\n"
        "- `VR 38,00 no vale refeição`\n"
        "- `Salário 5000` (receita)\n\n"
        "O bot extrairá o valor, descrição e instrumento automaticamente.\n"
        "Se a categoria não for óbvia, usará 'Outros' e você pode corrigir depois.\n"
        "Use /orcamento para ver o resumo do mês."
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