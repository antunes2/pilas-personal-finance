"""Main entry point for the personal finance Telegram bot.

Phase 1: Core recording - /start, /ajuda, /adicionar, natural messages.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from pilas_personal_finance.bot.handlers import start_command, ajuda_command, adicionar_command, handle_message
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


def get_supabase() -> create_client:
    """Get Supabase client instance."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY")
    return create_client(supabase_url, supabase_key)


async def post_init(application: Application):
    """Called after the application is initialized."""
    logger.info("Bot initialized successfully")


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