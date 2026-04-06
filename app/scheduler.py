"""APScheduler — daily medication check-in push messages.

Sends a morning push message to each user asking if they've taken their medication.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services import line_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Hardcoded user list for prototype — in production, query from DB
_registered_users: list[str] = []


def register_user(line_user_id: str) -> None:
    """Register a user for daily check-in push messages."""
    if line_user_id not in _registered_users:
        _registered_users.append(line_user_id)
        logger.info("Registered user for daily check-in: %s", line_user_id)


def unregister_user(line_user_id: str) -> None:
    """Unregister a user from daily check-in push messages."""
    if line_user_id in _registered_users:
        _registered_users.remove(line_user_id)


async def send_daily_checkin() -> None:
    """Send daily check-in message to all registered users.

    Runs at 08:00 Asia/Taipei every day.
    """
    if not _registered_users:
        logger.info("No registered users for daily check-in")
        return

    message = "早安！今天的藥都吃了嗎？🌞\n吃了的話跟我說一聲，我幫您記錄。"

    for user_id in _registered_users:
        try:
            await line_service.push_text(user_id, message)
            logger.info("Daily check-in sent to user: %s", user_id)
        except Exception:
            logger.warning("Failed to send check-in to user: %s", user_id)


def start_scheduler() -> None:
    """Start the APScheduler with daily check-in job."""
    scheduler.add_job(
        send_daily_checkin,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Taipei"),
        id="daily_checkin",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — daily check-in at 08:00 Asia/Taipei")


def stop_scheduler() -> None:
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
