"""Onboarding and consent handler for new LINE users.

PDPA (Taiwan Personal Data Protection Act) requires explicit consent
before storing health data. This handler manages:
- Welcome message for new users
- Consent collection
- Data deletion requests
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import line_service

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = (
    "您好！我是 MedBuddy 🤖，您的用藥小幫手。\n\n"
    "我可以幫您：\n"
    "• 用語音或文字了解藥物的作用\n"
    "• 檢查藥物之間的交互作用\n"
    "• 每天提醒您吃藥\n\n"
    "📋 使用須知：\n"
    "MedBuddy 會記錄您的用藥資訊，僅用於提醒和健康管理。"
    "您可以隨時傳送「刪除我的資料」來刪除所有記錄。\n\n"
    "繼續使用即表示您同意。請問您今天想了解什麼藥呢？"
)

CONSENT_RECORDED_MESSAGE = "已記錄您的同意。您可以隨時傳送「刪除我的資料」來刪除所有記錄。"

DATA_DELETED_MESSAGE = (
    "已刪除您的所有資料，包括用藥記錄和對話紀錄。\n"
    "如果您想重新開始使用 MedBuddy，請隨時傳送任何訊息。"
)

DELETE_COMMAND = "刪除我的資料"


async def handle_follow_event(user_id: str, session: AsyncSession) -> None:
    """Handle a new user following the MedBuddy LINE account.

    Creates user record and sends welcome message with consent notice.
    """
    # Check if user already exists
    result = await session.execute(select(User).where(User.line_user_id == user_id))
    existing = result.scalar_one_or_none()

    if existing is None:
        user = User(
            line_user_id=user_id,
            consent_given_at=datetime.now(UTC),
            onboarding_completed=False,
        )
        session.add(user)
        await session.commit()
        logger.info("New user created: %s", user_id)

    await line_service.push_text(user_id, WELCOME_MESSAGE)


async def handle_data_deletion(user_id: str, session: AsyncSession) -> bool:
    """Handle a user's request to delete all their data.

    Returns True if data was deleted, False if user not found.
    """
    result = await session.execute(select(User).where(User.line_user_id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        await line_service.push_text(user_id, "找不到您的資料。您可能已經刪除過了。")
        return False

    await session.delete(user)
    await session.commit()
    logger.info("User data deleted: %s", user_id)

    await line_service.push_text(user_id, DATA_DELETED_MESSAGE)
    return True


def is_delete_command(text: str) -> bool:
    """Check if the user's message is a data deletion request."""
    return text.strip() == DELETE_COMMAND


async def ensure_user_exists(user_id: str, session: AsyncSession) -> User:
    """Get or create a user record. Records consent on first interaction."""
    result = await session.execute(select(User).where(User.line_user_id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            line_user_id=user_id,
            consent_given_at=datetime.now(UTC),
            onboarding_completed=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user
