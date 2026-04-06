"""Conversation history model — stores encrypted chat messages."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationHistory(Base):
    """A single message in a user's conversation history.

    Content is AES-256 encrypted at the application layer.
    """

    __tablename__ = "conversation_history"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    content_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    message_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="text",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="conversations")  # noqa: F821
