"""Middleware classes for the telegram bot."""

from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from config import ADMIN_USER_IDS, THROTTLE_RATE, setup_logging

logger = setup_logging("telegram_middlewares")


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
