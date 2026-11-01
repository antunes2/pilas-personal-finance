"""Keyboards for Phase 1.

Reply keyboards for user interaction with the bot.
"""

from telegram import KeyboardButton, ReplyKeyboardMarkup


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


def get_category_keyboard(categories: list) -> ReplyKeyboardMarkup:
    """Keyboard with category buttons for selection.

    Pass a list of category name strings.
    """
    if not categories:
        buttons = [[KeyboardButton("Outros")]]
    else:
        # Show up to 5 categories per row
        rows = []
        row = []
        for i, cat in enumerate(categories):
            row.append(KeyboardButton(cat))
            if len(row) == 5 or i == len(categories) - 1:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        buttons = rows

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_instrument_keyboard(instruments: list) -> ReplyKeyboardMarkup:
    """Keyboard with payment instrument buttons."""
    if not instruments:
        buttons = [[KeyboardButton("Outros")]]
    else:
        buttons = [[KeyboardButton(inst["name"]) for inst in instruments[i:i+3]] 
                   for i in range(0, len(instruments), 3)]
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)