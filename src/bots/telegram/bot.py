"""Core telegram bot implementation for exchange rates."""

import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.chat_action import ChatActionMiddleware
from dotenv import load_dotenv

# Import modules from the refactored structure
from config import SUBSCRIPTIONS_FILE, TELEGRAM_BOT_TOKEN, setup_logging
from scrapers.minfin_scraper import MinfinExchangeRateScraper

from .handlers import admin_router, main_router, set_subscription_manager
from .middlewares import ErrorHandler, ThrottlingMiddleware
from .subscription import SubscriptionManager, UserSubscription
from .utils import format_exchange_rates

logger = setup_logging("telegram_bot")
load_dotenv()

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Check .env file.")

# Store background tasks
background_tasks = set()

# Initialize the subscription manager
subscription_manager = SubscriptionManager(SUBSCRIPTIONS_FILE)
# Set the subscription manager for handlers
set_subscription_manager(subscription_manager)


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

        # Ensure any existing webhook is removed before starting polling
        logger.info("Removing any existing webhook...")
        await bot.delete_webhook(drop_pending_updates=True)

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
