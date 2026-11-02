"""Main entry point for the personal finance Telegram bot.

Phase 1: Core recording - /start, /ajuda, /adicionar, natural messages.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from pilas_personal_finance.bot.handlers import (
    start_command, ajuda_command, adicionar_command, handle_message,
    fixos_command, fixos_adicionar_command, fixos_pagos_command,
    pagar_command, receber_command, list_receivables_command,
    registrar_recebimento_command, orcamento_command,
    cartoes_command, categorias_command, relatorio_command,
    resumo_command, analise_command, salario_command, beneficios_command,
)
from pilas_personal_finance.bot.keyboards import get_main_keyboard
from supabase import create_client

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

COMMAND_LIST = [
    ("start", "Iniciar e identificar usuário"),
    ("ajuda", "Ajuda e exemplos"),
    ("adicionar", "Registrar despesa/receita"),
    ("orcamento", "Orçamento: disponível agora e projetado"),
    ("fixos", "Despesas fixas (adicionar/pagos)"),
    ("fixos_adicionar", "Cadastrar despesa fixa"),
    ("fixos_pagos", "Fixas: pagas e pendentes"),
    ("pagar", "Marcar fixa como paga"),
    ("receber", "Registrar 'me devem'"),
    ("recebimentos", "Listar contas a receber"),
    ("registrar", "Registrar recebimento parcial"),
    ("cartoes", "Listar instrumentos de pagamento"),
    ("categorias", "Listar categorias válidas"),
    ("relatorio", "Relatório HTML (Fase 5 em breve)"),
    ("resumo", "Resumo rápido do mês"),
    ("analise", "Análise textual por IA"),
    ("salario", "Configurar salário bruto"),
    ("beneficios", "Configurar benefício fixo"),
]


def get_supabase() -> create_client:
    """Get Supabase client instance."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY")
    return create_client(supabase_url, supabase_key)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Central error handler - logs and doesn't crash the bot."""
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)


async def post_init(application: Application):
    """Called after the application is initialized."""
    await application.bot.set_my_commands(COMMAND_LIST)
    logger.info("Bot initialized with command menu (%d commands)", len(COMMAND_LIST))


def main():
    """Start the bot."""
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment")
        return

    application = Application.builder().token(telegram_token).post_init(post_init).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("ajuda", ajuda_command))
    application.add_handler(CommandHandler("adicionar", adicionar_command))
    application.add_handler(CommandHandler("orcamento", orcamento_command))
    application.add_handler(CommandHandler("fixos", fixos_command))
    application.add_handler(CommandHandler("fixos_adicionar", fixos_adicionar_command))
    application.add_handler(CommandHandler("fixos_pagos", fixos_pagos_command))
    application.add_handler(CommandHandler("pagar", pagar_command))
    application.add_handler(CommandHandler("receber", receber_command))
    application.add_handler(CommandHandler("recebimentos", list_receivables_command))
    application.add_handler(CommandHandler("registrar", registrar_recebimento_command))
    application.add_handler(CommandHandler("cartoes", cartoes_command))
    application.add_handler(CommandHandler("categorias", categorias_command))
    application.add_handler(CommandHandler("relatorio", relatorio_command))
    application.add_handler(CommandHandler("resumo", resumo_command))
    application.add_handler(CommandHandler("analise", analise_command))
    application.add_handler(CommandHandler("salario", salario_command))
    application.add_handler(CommandHandler("beneficios", beneficios_command))

    # Central error handler
    application.add_error_handler(on_error)
    
    # Add natural message handler (must be after command handlers)
    # We handle all text that doesn't start with /
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    # Start polling
    logger.info("Starting bot polling...")
    application.run_polling()
    

if __name__ == "__main__":
    main()