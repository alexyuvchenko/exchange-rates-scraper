"""Command handlers for the telegram bot."""

import asyncio
import re

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove

from config import DEFAULT_CURRENCIES, setup_logging
from scrapers.minfin_scraper import MinfinExchangeRateScraper

from .subscription import SubscriptionManager, UserSubscription
from .utils import (
    create_currency_keyboard,
    create_currency_selection_keyboard,
    create_main_menu_keyboard,
    create_schedule_keyboard,
    create_time_keyboard,
    format_exchange_rates,
    is_admin,
)

logger = setup_logging("telegram_handlers")

# Create routers
main_router = Router(name="main")
admin_router = Router(name="admin")


# States
class SubscriptionStates(StatesGroup):
    selecting_currencies = State()
    selecting_schedule = State()
    selecting_time = State()


# We'll use dependency injection instead of direct import
# to avoid circular imports
subscription_manager = None


def set_subscription_manager(manager: SubscriptionManager) -> None:
    """Set the subscription manager instance."""
    global subscription_manager
    subscription_manager = manager


@main_router.message(CommandStart())
async def send_welcome(message: Message) -> None:
    welcome_text = (
        "🏦 <b>Exchange Rates Bot</b>\n\n"
        "Welcome! I can help you track the best exchange rates from banks.\n\n"
        "Please use the menu below to navigate:"
    )
    await message.reply(
        welcome_text, parse_mode=ParseMode.HTML, reply_markup=create_main_menu_keyboard()
    )


@main_router.message(Command("help"))
async def send_help(message: Message) -> None:
    help_text = (
        "🏦 <b>Exchange Rates Bot Help</b>\n\n"
        "I can help you track the best exchange rates from banks.\n\n"
        "<b>You can use the buttons below or these commands:</b>\n"
        "/rates - Get current exchange rates (USD, EUR, or all)\n"
        "/subscribe - Set up daily notifications\n"
        "/unsubscribe - Stop daily notifications\n"
        "/settings - View and change your settings\n"
        "/help - Show this message\n\n"
        "Stay updated with the best exchange rates!"
    )
    await message.reply(
        help_text, parse_mode=ParseMode.HTML, reply_markup=create_main_menu_keyboard()
    )


# Handle button presses from the main menu
@main_router.message(F.text == "📊 Exchange Rates")
async def menu_get_rates(message: Message, state: FSMContext) -> None:
    await get_rates(message, state)


@main_router.message(F.text == "📝 Subscribe")
async def menu_subscribe(message: Message, state: FSMContext) -> None:
    await subscribe_command(message, state)


@main_router.message(F.text == "⚙️ Settings")
async def menu_settings(message: Message) -> None:
    await settings_command(message)


@main_router.message(F.text == "❌ Unsubscribe")
async def menu_unsubscribe(message: Message) -> None:
    await unsubscribe_command(message)


@main_router.message(F.text == "ℹ️ Help")
async def menu_help(message: Message) -> None:
    await send_help(message)


@main_router.message(Command("rates"))
async def get_rates(message: Message, state: FSMContext) -> None:
    keyboard = create_currency_selection_keyboard()
    await message.reply("Please select a currency:", reply_markup=keyboard)
    await state.update_data(command_source="rates")
    await state.set_state(SubscriptionStates.selecting_currencies)


@main_router.message(Command("subscribe"))
async def subscribe_command(message: Message, state: FSMContext) -> None:
    user_id = str(message.from_user.id)
    if not subscription_manager.get(user_id):
        subscription_manager.add_or_update(user_id, UserSubscription())

    keyboard = create_currency_keyboard()
    await message.reply("Select currencies you're interested in:", reply_markup=keyboard)
    await state.update_data(command_source="subscribe")
    await state.set_state(SubscriptionStates.selecting_currencies)


@main_router.message(Command("unsubscribe"))
async def unsubscribe_command(message: Message) -> None:
    user_id = str(message.from_user.id)
    if subscription_manager.remove(user_id):
        await message.reply(
            "You have been unsubscribed from all notifications.",
            reply_markup=create_main_menu_keyboard(),
        )
    else:
        await message.reply("You don't have any active subscriptions.")


@main_router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    user_id = str(message.from_user.id)
    subscription = subscription_manager.get(user_id)

    if subscription:
        currencies = ", ".join(currency.upper() for currency in subscription.currencies)
        settings_text = (
            f"<b>Your Subscription Settings:</b>\n\n"
            f"<b>Currencies:</b> {currencies}\n"
            f"<b>Schedule:</b> {subscription.schedule.capitalize()}\n"
            f"<b>Time:</b> {subscription.time}\n\n"
            f"Use /subscribe to change settings or /unsubscribe to cancel."
        )
        await message.reply(
            settings_text, parse_mode=ParseMode.HTML, reply_markup=create_main_menu_keyboard()
        )
    else:
        await message.reply(
            "You don't have any active subscriptions. Use /subscribe to set one up.",
            reply_markup=create_main_menu_keyboard(),
        )


@main_router.message(SubscriptionStates.selecting_currencies)
async def process_currency_selection(message: Message, state: FSMContext) -> None:
    # Get the data to determine which command triggered this state
    data = await state.get_data()
    command_source = data.get("command_source", "subscribe")

    # If this state was triggered by the /rates command
    if command_source == "rates":
        if message.text in ["USD", "EUR", "All currencies"]:
            await state.clear()

            currencies = []
            if message.text == "All currencies":
                currencies = DEFAULT_CURRENCIES
                await message.reply(
                    "Fetching rates for all currencies... Please wait.",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                currencies = [message.text.lower()]
                await message.reply(
                    f"Fetching rates for {message.text}... Please wait.",
                    reply_markup=ReplyKeyboardRemove(),
                )

            try:
                scraper = MinfinExchangeRateScraper()

                for currency in currencies:
                    try:
                        data = await scraper.get_exchange_rates(currency)
                        formatted_message = await format_exchange_rates(data, currency)
                        await message.answer(formatted_message, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logger.error(f"Error fetching rates for {currency}: {e}")
                        await message.answer(f"Error fetching rates for {currency}: {str(e)}")

                # Return to main menu after displaying rates
                await message.answer(
                    "What would you like to do next?", reply_markup=create_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"Error fetching rates: {e}")
                await message.answer(
                    "An error occurred while fetching rates. Please try again later.",
                    reply_markup=create_main_menu_keyboard(),
                )
        else:
            await message.reply("Please select USD, EUR, or All currencies")
        return

    # Original subscription logic follows
    user_id = str(message.from_user.id)
    subscription = subscription_manager.get(user_id)

    if not subscription:
        subscription = UserSubscription()
        subscription_manager.add_or_update(user_id, subscription)

    if message.text.lower() == "done":
        if not subscription.currencies:
            await message.reply("You haven't selected any currencies. Please select at least one.")
            return

        keyboard = create_schedule_keyboard()
        await message.reply("How often would you like to receive updates?", reply_markup=keyboard)
        await state.set_state(SubscriptionStates.selecting_schedule)
        return

    currency = message.text.lower()
    if currency in DEFAULT_CURRENCIES:
        if currency not in subscription.currencies:
            subscription.currencies.append(currency)
            subscription_manager.add_or_update(user_id, subscription)
            await message.reply(f"Added {currency.upper()} to your subscription.")
        else:
            await message.reply(f"You've already subscribed to {currency.upper()}.")
    else:
        await message.reply(f"Currency {message.text} is not supported.")


@main_router.message(SubscriptionStates.selecting_schedule)
async def process_schedule_selection(message: Message, state: FSMContext) -> None:
    user_id = str(message.from_user.id)
    subscription = subscription_manager.get(user_id)

    if not subscription:
        await state.clear()
        await message.reply(
            "There was an error with your subscription. Please try again with /subscribe."
        )
        return

    schedule = message.text.lower()
    if schedule in ["daily", "weekly"]:
        subscription.schedule = schedule
        subscription_manager.add_or_update(user_id, subscription)

        keyboard = create_time_keyboard()
        await message.reply(
            "At what time would you like to receive updates?", reply_markup=keyboard
        )
        await state.set_state(SubscriptionStates.selecting_time)
    else:
        await message.reply("Please select Daily or Weekly.")


@main_router.message(SubscriptionStates.selecting_time)
async def process_time_selection(message: Message, state: FSMContext) -> None:
    # Time validation
    time_pattern = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
    if not time_pattern.match(message.text):
        await message.reply("Please enter a valid time in the format HH:MM (24-hour format).")
        return

    user_id = str(message.from_user.id)
    subscription = subscription_manager.get(user_id)

    if not subscription:
        await message.reply(
            "Something went wrong with your subscription. Please start again with /subscribe."
        )
        await state.clear()
        return

    subscription.time = message.text
    subscription_manager.add_or_update(user_id, subscription)

    # Format currencies for display
    currencies = ", ".join(currency.upper() for currency in subscription.currencies)

    # Send a confirmation message
    confirmation = (
        f"✅ <b>Subscription Confirmed!</b>\n\n"
        f"You will receive {subscription.schedule} exchange rate updates for {currencies} at {subscription.time}.\n\n"
        f"Use /settings to view your settings or /unsubscribe to cancel."
    )
    await message.reply(
        confirmation, parse_mode=ParseMode.HTML, reply_markup=create_main_menu_keyboard()
    )
    await state.clear()


@admin_router.message(Command("stats"))
async def admin_stats(message: Message) -> None:
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.reply("This command is only available to administrators.")
        return

    total_subscriptions = subscription_manager.count()
    currency_stats = {}

    for _, subscription in subscription_manager.subscriptions.items():
        for currency in subscription.currencies:
            currency_stats[currency] = currency_stats.get(currency, 0) + 1

    stats_text = (
        "<b>📊 Bot Statistics</b>\n\n"
        f"<b>Total subscriptions:</b> {total_subscriptions}\n\n"
        "<b>Currencies subscribed:</b>\n"
    )

    for currency, count in sorted(currency_stats.items(), key=lambda x: x[1], reverse=True):
        stats_text += f"- {currency.upper()}: {count}\n"

    await message.reply(stats_text, parse_mode=ParseMode.HTML)


@admin_router.message(Command("broadcast"))
async def admin_broadcast_command(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.reply("This command is only available to administrators.")
        return

    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2:
        await message.reply(
            "Please provide a message to broadcast. Usage: /broadcast Your message here"
        )
        return

    broadcast_message = command_parts[1]

    await message.reply(
        f"You are about to send this message to {subscription_manager.count()} subscribers:\n\n"
        f"{broadcast_message}\n\n"
        "Are you sure you want to send this? Reply with 'yes' to confirm or 'no' to cancel."
    )

    await state.update_data(broadcast_message=broadcast_message)


@admin_router.message(F.text.lower() == "yes")
async def confirm_broadcast(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    data = await state.get_data()
    broadcast_message = data.get("broadcast_message")

    if not broadcast_message:
        await message.reply("No broadcast message found. Please use /broadcast again.")
        return

    await message.reply("Broadcasting message to all subscribers...")

    sent_count = 0
    error_count = 0

    for user_id in subscription_manager.subscriptions.keys():
        try:
            await message.bot.send_message(
                chat_id=user_id, text=broadcast_message, parse_mode=ParseMode.HTML
            )
            sent_count += 1
            # Add a small delay to avoid hitting rate limits
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            error_count += 1

    await message.reply(f"Broadcast complete: {sent_count} messages sent, {error_count} failed.")
    await state.clear()


@admin_router.message(F.text.lower() == "no")
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    await message.reply("Broadcast cancelled.")
    await state.clear()
