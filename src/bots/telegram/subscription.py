"""Subscription management for the telegram bot."""

import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import setup_logging

logger = setup_logging("telegram_subscription")


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
