"""Check-in handler — processes daily medication adherence responses.

When a user responds to the daily check-in push message, this handler
parses their response via DSPy and logs adherence to the database.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.adherence import AdherenceLog
from app.models.medication import Medication
from app.models.user import User
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def log_adherence(
    user_id: str,
    taken_drugs: list[str],
    missed_drugs: list[str],
    source: str,
    session: AsyncSession,
) -> None:
    """Log medication adherence to the database.

    Args:
        user_id: LINE user ID.
        taken_drugs: List of drug names the user confirmed taking.
        missed_drugs: List of drug names the user missed.
        source: How the report was made (voice / text / push_response).
        session: Async database session.
    """
    result = await session.execute(select(User).where(User.line_user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("Adherence log for unknown user: %s", user_id)
        return

    # Get user's active medications
    med_result = await session.execute(
        select(Medication).where(
            Medication.user_id == user.id,
            Medication.is_active.is_(True),
        )
    )
    medications = med_result.scalars().all()

    now = datetime.now(UTC)

    for med in medications:
        drug_name = decrypt(med.drug_name_en_encrypted)
        drug_name_lower = drug_name.lower()

        if any(t.lower() == drug_name_lower for t in taken_drugs):
            status = "taken"
            taken_at = now
        elif any(m.lower() == drug_name_lower for m in missed_drugs):
            status = "missed"
            taken_at = None
        else:
            continue

        log_entry = AdherenceLog(
            user_id=user.id,
            medication_id=med.id,
            scheduled_at=now,
            taken_at=taken_at,
            status=status,
            source=source,
        )
        session.add(log_entry)

    await session.commit()
    logger.info(
        "Adherence logged for user %s: %d taken, %d missed",
        user_id,
        len(taken_drugs),
        len(missed_drugs),
    )
