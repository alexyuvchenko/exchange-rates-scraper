"""Utility functions for the telegram bot."""

from datetime import datetime
from typing import Any, Dict, List

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from config import ADMIN_USER_IDS, DEFAULT_CURRENCIES


async def format_exchange_rates(data: List[Dict[str, Any]], currency: str) -> str:
    """Format exchange rates data for display in a message."""
    if not data:
        return f"No exchange rate data available for {currency.upper()}"

    top_banks = data[:15]
    message = f"🏦 <b>Exchange Rates for {currency.upper()}</b>\n\n"
    message += f"<i>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>\n\n"

    for bank in top_banks:
        message += f"<b>{bank['bank']}</b>\n"

        if bank.get("cash_buy") and bank.get("cash_sell"):
            message += f"💵 Cash: Buy {bank['cash_buy']} / Sell {bank['cash_sell']}\n"

        if bank.get("card_buy") and bank.get("card_sell"):
            message += f"💳 Card: Buy {bank['card_buy']} / Sell {bank['card_sell']}\n"

        message += f"⏱ Updated: {bank.get('update_time', 'N/A')}\n\n"

    message += f"<i>Data from minfin.com.ua</i>"
    return message


def create_currency_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with currency options."""
    builder = ReplyKeyboardBuilder()
    for currency in DEFAULT_CURRENCIES:
        builder.add(KeyboardButton(text=currency.upper()))
    builder.add(KeyboardButton(text="Done"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_schedule_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with schedule options."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Daily"))
    builder.add(KeyboardButton(text="Weekly"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_time_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard with time options."""
    builder = ReplyKeyboardBuilder()
    for hour in ["09:30", "11:30", "13:30", "15:30", "17:30"]:
        builder.add(KeyboardButton(text=hour))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Create the main menu keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Exchange Rates"))
    builder.add(KeyboardButton(text="📝 Subscribe"))
    builder.add(KeyboardButton(text="⚙️ Settings"))
    builder.add(KeyboardButton(text="❌ Unsubscribe"))
    builder.add(KeyboardButton(text="ℹ️ Help"))
    builder.adjust(2)  # Two buttons per row
    return builder.as_markup(resize_keyboard=True)


def create_currency_selection_keyboard() -> ReplyKeyboardMarkup:
    """Create a keyboard for currency selection."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="USD"), KeyboardButton(text="EUR")],
            [KeyboardButton(text="All currencies")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def is_admin(user_id: int) -> bool:
    """Check if a user is an admin."""
    return user_id in ADMIN_USER_IDS
