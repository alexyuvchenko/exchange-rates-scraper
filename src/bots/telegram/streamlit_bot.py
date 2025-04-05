import asyncio
import concurrent.futures
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

# Add parent directories to path to make imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Import bot dependencies
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

# Import project modules
from config import TELEGRAM_BOT_TOKEN, setup_logging
from scrapers.minfin_scraper import MinfinExchangeRateScraper

# Setup logger
logger = setup_logging("streamlit_telegram_bot")

# Executor for running async functions from sync code
executor = concurrent.futures.ThreadPoolExecutor()


class BotState:
    """Class to manage the Telegram bot state and subscriptions."""

    def __init__(self):
        """Initialize bot state."""
        self.is_running = False
        self.bot = None
        self.dispatcher = None

        # Bot data
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.subscriptions_file = os.path.join("data", "subscriptions.json")

    def load_subscriptions(self) -> None:
        """Load user subscriptions from file."""
        try:
            if os.path.exists(self.subscriptions_file):
                with open(self.subscriptions_file, "r") as f:
                    self.subscriptions = json.load(f)
                logger.info(f"Loaded {len(self.subscriptions)} subscriptions")
            else:
                logger.info("No subscriptions file found, starting with empty subscriptions")
                self.subscriptions = {}
        except Exception as e:
            logger.error(f"Error loading subscriptions: {e}")
            self.subscriptions = {}

    def save_subscriptions(self) -> None:
        """Save user subscriptions to file."""
        try:
            os.makedirs(os.path.dirname(self.subscriptions_file), exist_ok=True)
            with open(self.subscriptions_file, "w") as f:
                json.dump(self.subscriptions, f)
            logger.info(f"Saved {len(self.subscriptions)} subscriptions")
        except Exception as e:
            logger.error(f"Error saving subscriptions: {e}")


# Create a global bot state
bot_state = BotState()


# Command handlers
async def start_handler(message: Message) -> None:
    """Handle the /start command."""
    await message.answer(
        "👋 Welcome to Minfin Exchange Rates Bot!\n\n"
        "This bot provides real-time currency exchange rates from minfin.com.ua.\n\n"
        "Use /help to see available commands."
    )


async def help_handler(message: Message) -> None:
    """Handle the /help command."""
    await message.answer(
        "📚 Available commands:\n\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/rates - Get current exchange rates for major currencies\n"
        "/subscribe - Subscribe to daily exchange rate updates\n"
        "/unsubscribe - Unsubscribe from updates\n"
        "/status - Check bot status"
    )


async def get_exchange_rates(currencies: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Get current exchange rates.

    Args:
        currencies: List of currency codes (default: ["usd", "eur"])

    Returns:
        List of exchange rate data dictionaries
    """
    if currencies is None:
        currencies = ["usd", "eur"]

    scraper = MinfinExchangeRateScraper()
    results = []

    for currency in currencies:
        try:
            rates = await scraper.get_exchange_rates(currency)
            if rates:
                results.extend(rates)
        except Exception as e:
            logger.error(f"Error fetching rates for {currency}: {e}")

    return results


async def rates_handler(message: Message) -> None:
    """Handle the /rates command."""
    user_id = str(message.from_user.id)

    await message.answer("Fetching current exchange rates, please wait...")

    # Get user's preferred currencies or default to USD and EUR
    user_currencies = []
    if user_id in bot_state.subscriptions:
        user_currencies = [
            c.lower() for c in bot_state.subscriptions[user_id].get("currencies", ["USD", "EUR"])
        ]
    else:
        user_currencies = ["usd", "eur"]

    try:
        rates = await get_exchange_rates(user_currencies)

        if not rates:
            await message.answer("❌ Failed to fetch exchange rates. Please try again later.")
            return

        # Group rates by currency
        by_currency = {}
        for rate in rates:
            currency = rate["currency"]
            if currency not in by_currency:
                by_currency[currency] = []
            by_currency[currency].append(rate)

        # Format response with best rates for each currency
        response_text = format_best_rates(by_currency)

        await message.answer(response_text)

    except Exception as e:
        logger.error(f"Error in rates handler: {e}")
        await message.answer("❌ An error occurred while fetching rates. Please try again later.")


def format_best_rates(by_currency: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    Format the best rates for each currency into a message.

    Args:
        by_currency: Dictionary mapping currency codes to lists of rate data

    Returns:
        Formatted message string
    """
    response_text = "💰 Current Exchange Rates (Best Rates):\n\n"

    for currency, currency_rates in by_currency.items():
        # Sort by cash sell rate (ascending)
        best_rates = sorted(
            [r for r in currency_rates if r.get("cash_sell")],
            key=lambda x: float(x["cash_sell"]) if x["cash_sell"] else float("inf"),
        )

        if best_rates:
            best_rate = best_rates[0]
            response_text += f"{currency}:\n"
            response_text += f"🏦 {best_rate['bank']}\n"
            response_text += (
                f"Cash: Buy {best_rate['cash_buy']} / Sell {best_rate['cash_sell']} UAH\n"
            )

            if best_rate.get("card_buy") and best_rate.get("card_sell"):
                response_text += (
                    f"Card: Buy {best_rate['card_buy']} / Sell {best_rate['card_sell']} UAH\n"
                )

            response_text += "\n"

    return response_text


async def subscribe_handler(message: Message) -> None:
    """Handle the /subscribe command."""
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name

    if user_id in bot_state.subscriptions:
        await message.answer("You are already subscribed to updates!")
    else:
        bot_state.subscriptions[user_id] = {
            "username": username,
            "subscribed_at": time.time(),
            "currencies": ["USD", "EUR"],
        }
        bot_state.save_subscriptions()
        await message.answer("✅ You've been subscribed to daily exchange rate updates!")


async def unsubscribe_handler(message: Message) -> None:
    """Handle the /unsubscribe command."""
    user_id = str(message.from_user.id)

    if user_id in bot_state.subscriptions:
        del bot_state.subscriptions[user_id]
        bot_state.save_subscriptions()
        await message.answer("❌ You've been unsubscribed from updates.")
    else:
        await message.answer("You are not subscribed to updates.")


async def status_handler(message: Message) -> None:
    """Handle the /status command."""
    await message.answer(
        "✅ Bot is running!\n" f"Active subscribers: {len(bot_state.subscriptions)}"
    )


# Bot setup and management functions
async def setup_bot() -> Tuple[Optional[Bot], Optional[Dispatcher]]:
    """
    Set up the bot and dispatcher.

    Returns:
        Tuple of (Bot, Dispatcher) or (None, None) if setup fails
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Bot token is not set in the config file")
        return None, None

    try:
        # Create a bot instance
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        # Create a dispatcher
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        # Create a router
        router = Router()

        # Register command handlers
        router.message.register(start_handler, CommandStart())
        router.message.register(help_handler, Command("help"))
        router.message.register(rates_handler, Command("rates"))
        router.message.register(subscribe_handler, Command("subscribe"))
        router.message.register(unsubscribe_handler, Command("unsubscribe"))
        router.message.register(status_handler, Command("status"))

        # Add router to dispatcher
        dp.include_router(router)

        return bot, dp
    except Exception as e:
        logger.error(f"Error setting up bot: {e}")
        return None, None


async def process_update(update_json: Dict[str, Any]) -> bool:
    """
    Process an update received from Telegram.

    Args:
        update_json: Update data from Telegram webhook

    Returns:
        True if update was processed successfully, False otherwise
    """
    if not bot_state.bot or not bot_state.dispatcher:
        logger.error("Bot or dispatcher not initialized")
        return False

    try:
        await bot_state.dispatcher.feed_update(bot=bot_state.bot, update=update_json)
        return True
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return False


async def init_bot_async() -> bool:
    """
    Initialize the bot asynchronously.

    Returns:
        True if initialization was successful, False otherwise
    """
    try:
        bot, dp = await setup_bot()
        if not bot or not dp:
            return False

        bot_state.bot = bot
        bot_state.dispatcher = dp
        bot_state.load_subscriptions()

        return True
    except Exception as e:
        logger.error(f"Error initializing bot: {e}")
        return False


def run_async_in_thread(coro):
    """
    Run an async coroutine in a sync context using a ThreadPoolExecutor.

    Args:
        coro: Coroutine to run

    Returns:
        Result of the coroutine
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def init_bot() -> bool:
    """
    Initialize the bot synchronously.

    Returns:
        True if initialization was successful, False otherwise
    """
    return executor.submit(run_async_in_thread, init_bot_async()).result()


def send_message(chat_id: Union[str, int], text: str) -> bool:
    """
    Send a message to a user.

    Args:
        chat_id: User's chat ID
        text: Message text

    Returns:
        True if message was sent successfully, False otherwise
    """
    if not bot_state.bot:
        logger.error("Bot not initialized")
        return False

    async def _send():
        try:
            await bot_state.bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    return executor.submit(run_async_in_thread, _send()).result()


def broadcast_message(text: str) -> int:
    """
    Send a message to all subscribers.

    Args:
        text: Message text

    Returns:
        Number of users message was successfully sent to
    """
    if not bot_state.bot:
        logger.error("Bot not initialized")
        return 0

    async def _broadcast():
        sent_count = 0
        for user_id in bot_state.subscriptions:
            try:
                await bot_state.bot.send_message(chat_id=user_id, text=text)
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
        return sent_count

    return executor.submit(run_async_in_thread, _broadcast()).result()


def get_latest_rates() -> List[Dict[str, Any]]:
    """
    Get the latest exchange rates.

    Returns:
        List of exchange rate data dictionaries
    """

    async def _get_rates():
        return await get_exchange_rates()

    return executor.submit(run_async_in_thread, _get_rates()).result()


def run_bot_thread() -> None:
    """Run the bot in a separate thread."""
    if bot_state.is_running:
        logger.warning("Bot is already running!")
        return

    try:
        # Initialize the bot
        if init_bot():
            bot_state.is_running = True
            logger.info("Bot initialized successfully")
        else:
            logger.error("Failed to initialize bot")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        bot_state.is_running = False


def stop_bot_thread() -> None:
    """Stop the bot thread."""
    if not bot_state.is_running:
        logger.warning("Bot is not running!")
        return

    try:
        logger.info("Stopping bot...")
        bot_state.is_running = False
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Error stopping bot: {e}")


def get_bot_status() -> Dict[str, Any]:
    """
    Get the current status of the bot.

    Returns:
        Dict with bot status information
    """
    return {
        "is_running": bot_state.is_running,
        "subscriber_count": len(bot_state.subscriptions),
        "token_configured": bool(TELEGRAM_BOT_TOKEN),
    }
