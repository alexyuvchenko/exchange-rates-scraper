"""Core telegram bot implementation for exchange rates."""

import asyncio
import json
import os
import re
from datetime import datetime, time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.chat_action import ChatActionMiddleware
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv

from config import DATA_DIR, DEFAULT_CURRENCIES, setup_logging
from scrapers.minfin_scraper import MinfinExchangeRateScraper

logger = setup_logging("telegram_bot")
load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Check .env file.")

ADMIN_USER_IDS = (
    set(map(int, os.environ.get("ADMIN_USER_IDS", "").split(",")))
    if os.environ.get("ADMIN_USER_IDS")
    else set()
)
SUBSCRIPTIONS_FILE = DATA_DIR / "subscriptions.json"

# Command throttling settings (seconds)
THROTTLE_RATE = {"default": 2, "rates": 30, "subscribe": 60}

# Create routers
main_router = Router(name="main")
admin_router = Router(name="admin")

# Store background tasks
background_tasks = set()


class UserSubscription:
    def __init__(self, currencies: List[str] = None, schedule: str = "daily", time: str = "09:30"):
        self.currencies = currencies or []
        self.schedule = schedule
        self.time = time

    def to_dict(self) -> Dict[str, Any]:
        return {"currencies": self.currencies, "schedule": self.schedule, "time": self.time}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserSubscription":
        return cls(
            currencies=data.get("currencies", []),
            schedule=data.get("schedule", "daily"),
            time=data.get("time", "09:00"),
        )

    def get_next_notification_time(self) -> Optional[datetime]:
        """Calculate when the next notification will be sent."""
        now = datetime.now()
        hours, minutes = map(int, self.time.split(":"))
        notification_time = time(hours, minutes)

        if self.schedule == "daily":
            return datetime.combine(now.date(), notification_time)
        elif self.schedule == "weekly" and now.weekday() == 6:  # Sunday
            return datetime.combine(now.date(), notification_time)
        return None


class SubscriptionManager:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.subscriptions: Dict[str, UserSubscription] = {}
        self.load()

    def load(self) -> None:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r") as f:
                    data = json.load(f)

                self.subscriptions = {
                    user_id: UserSubscription.from_dict(sub_data)
                    for user_id, sub_data in data.items()
                }
                logger.info(f"Loaded {len(self.subscriptions)} subscriptions")
            except Exception as e:
                logger.error(f"Error loading subscriptions: {e}")
                self.subscriptions = {}
        else:
            logger.info("No subscriptions file found, starting with empty subscriptions")
            self.subscriptions = {}

    def save(self) -> None:
        try:
            data = {
                user_id: subscription.to_dict()
                for user_id, subscription in self.subscriptions.items()
            }

            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.subscriptions)} subscriptions")
        except Exception as e:
            logger.error(f"Error saving subscriptions: {e}")

    def get(self, user_id: str) -> Optional[UserSubscription]:
        return self.subscriptions.get(user_id)

    def add_or_update(self, user_id: str, subscription: UserSubscription) -> None:
        self.subscriptions[user_id] = subscription
        self.save()

    def remove(self, user_id: str) -> bool:
        if user_id in self.subscriptions:
            del self.subscriptions[user_id]
            self.save()
            return True
        return False

    def count(self) -> int:
        return len(self.subscriptions)

    def items(self) -> List[tuple]:
        return list(self.subscriptions.items())


class ErrorHandler:
    @staticmethod
    async def handle_error(event: Message, exception: Exception) -> bool:
        user_id = event.from_user.id if event.from_user else "Unknown"

        if isinstance(exception, TelegramAPIError):
            logger.error(f"Telegram API error for user {user_id}: {exception}")
            await event.answer(
                "Sorry, there was an error processing your request. Please try again later.",
                parse_mode=None,
            )
        else:
            logger.error(f"Unexpected error for user {user_id}: {exception}", exc_info=True)
            await event.answer(
                "An unexpected error occurred. Our team has been notified.", parse_mode=None
            )

            # Notify admins about unexpected errors
            for admin_id in ADMIN_USER_IDS:
                try:
                    bot = event.bot
                    await bot.send_message(
                        chat_id=admin_id,
                        text=f"❗ Error from user {user_id}:\n{str(exception)}",
                        parse_mode=None,
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")

        return True


class ThrottlingMiddleware:
    def __init__(self):
        self.rates = THROTTLE_RATE
        self.last_calls: Dict[tuple, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.text or not event.text.startswith("/"):
            return await handler(event, data)

        command = event.text.split()[0][1:].split("@")[0].lower()
        user_id = event.from_user.id

        rate = self.rates.get(command, self.rates["default"])
        key = (user_id, command)

        current_time = datetime.now().timestamp()
        if key in self.last_calls:
            time_passed = current_time - self.last_calls[key]
            if time_passed < rate:
                await event.answer(
                    f"Please wait {int(rate - time_passed)} seconds before using this command again."
                )
                return None

        self.last_calls[key] = current_time
        return await handler(event, data)


class SubscriptionStates(StatesGroup):
    selecting_currencies = State()
    selecting_schedule = State()
    selecting_time = State()


# Initialize the subscription manager
subscription_manager = SubscriptionManager(SUBSCRIPTIONS_FILE)


async def format_exchange_rates(data: List[Dict[str, Any]], currency: str) -> str:
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
    builder = ReplyKeyboardBuilder()
    for currency in DEFAULT_CURRENCIES:
        builder.add(KeyboardButton(text=currency.upper()))
    builder.add(KeyboardButton(text="Done"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_schedule_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Daily"))
    builder.add(KeyboardButton(text="Weekly"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_time_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for hour in ["09:30", "11:30", "13:30", "15:30", "17:30"]:
        builder.add(KeyboardButton(text=hour))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def create_main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Exchange Rates"))
    builder.add(KeyboardButton(text="📝 Subscribe"))
    builder.add(KeyboardButton(text="⚙️ Settings"))
    builder.add(KeyboardButton(text="❌ Unsubscribe"))
    builder.add(KeyboardButton(text="ℹ️ Help"))
    builder.adjust(2)  # Two buttons per row
    return builder.as_markup(resize_keyboard=True)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


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
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="USD"), KeyboardButton(text="EUR")],
            [KeyboardButton(text="All currencies")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
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


async def scheduled_job(bot: Bot) -> None:
    try:
        while True:
            try:
                current_time = datetime.now().strftime("%H:%M")
                current_day = datetime.now().weekday()  # 0-6 (Monday is 0)
                is_weekly_day = current_day == 6  # Sunday

                scraper = MinfinExchangeRateScraper()

                for user_id, subscription in subscription_manager.subscriptions.items():
                    if subscription.time == current_time:
                        should_send = subscription.schedule == "daily" or (
                            subscription.schedule == "weekly" and is_weekly_day
                        )

                        if should_send:
                            await send_notifications_to_user(user_id, subscription, scraper, bot)

                # Sleep for 1 minute
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in scheduled job: {e}")
                await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("Scheduled job was cancelled")
        subscription_manager.save()


async def send_notifications_to_user(
    user_id: str, subscription: UserSubscription, scraper: MinfinExchangeRateScraper, bot: Bot
) -> None:
    for currency in subscription.currencies:
        try:
            data = await scraper.get_exchange_rates(currency)
            formatted_message = await format_exchange_rates(data, currency)
            await bot.send_message(
                chat_id=user_id, text=formatted_message, parse_mode=ParseMode.HTML
            )
            logger.info(f"Sent notification to {user_id} for {currency}")
        except Exception as e:
            logger.error(f"Error sending notification to {user_id} for {currency}: {e}")


async def on_startup(bot: Bot) -> None:
    task = asyncio.create_task(scheduled_job(bot))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    logger.info("Bot started!")


async def on_shutdown(bot: Bot) -> None:
    subscription_manager.save()

    for task in background_tasks:
        task.cancel()

    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    logger.info("Bot is shutting down!")


async def start_bot() -> bool:
    """Start the Telegram bot for use from external modules."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Telegram bot token is not set")

    try:
        bot = Bot(
            token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

        dp = Dispatcher(storage=MemoryStorage())

        # Setup middlewares
        main_router.message.middleware(ThrottlingMiddleware())
        main_router.message.middleware(ChatActionMiddleware())

        # Setup error handler
        error_handler = ErrorHandler()
        dp.errors.register(error_handler.handle_error)

        # Include routers
        dp.include_router(main_router)
        dp.include_router(admin_router)

        # Register startup and shutdown handlers
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        logger.info("Starting bot...")
        await dp.start_polling(bot)
        return True
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(start_bot())
