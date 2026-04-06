"""Medication model — a user's tracked medications with encrypted fields."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Medication(Base):
    """A medication tracked for a user. Sensitive fields are AES-256 encrypted."""

    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Encrypted fields — stored as binary, decrypted in service layer
    drug_name_en_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    drug_name_zh_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    dosage_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    purpose_zh_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    # Non-sensitive fields — stored in plaintext
    rxcui: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    frequency: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    timing: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="medications")  # noqa: F821
    adherence_logs: Mapped[list["AdherenceLog"]] = relationship(  # noqa: F821
        back_populates="medication",
        cascade="all, delete-orphan",
    )
