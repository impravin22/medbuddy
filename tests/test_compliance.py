"""Compliance tests — consent, data deletion, rate limiting, adherence.

Covers PDPA, OWASP, and medical safety requirements from the plan.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers.onboarding_handler import (
    DELETE_COMMAND,
    is_delete_command,
)
from app.services.rate_limiter import clear, is_rate_limited


class TestRateLimiting:
    """Test per-user rate limiting."""

    def setup_method(self) -> None:
        """Clear rate limit state before each test."""
        clear()

    def test_allows_requests_under_limit(self) -> None:
        """Requests under the limit are allowed."""
        for _ in range(5):
            assert is_rate_limited("user-1") is False

    def test_blocks_requests_over_limit(self) -> None:
        """Requests over the limit are blocked."""
        with patch("app.services.rate_limiter.settings") as mock_settings:
            mock_settings.RATE_LIMIT_PER_USER = 3
            clear()
            assert is_rate_limited("user-1") is False
            assert is_rate_limited("user-1") is False
            assert is_rate_limited("user-1") is False
            # 4th request should be blocked
            assert is_rate_limited("user-1") is True

    def test_different_users_have_separate_limits(self) -> None:
        """Each user has their own rate limit counter."""
        with patch("app.services.rate_limiter.settings") as mock_settings:
            mock_settings.RATE_LIMIT_PER_USER = 2
            clear()
            assert is_rate_limited("user-1") is False
            assert is_rate_limited("user-1") is False
            assert is_rate_limited("user-1") is True
            # user-2 should still be allowed
            assert is_rate_limited("user-2") is False

    def test_window_expires(self) -> None:
        """Rate limit resets after the window expires."""
        with (
            patch("app.services.rate_limiter.settings") as mock_settings,
            patch("app.services.rate_limiter._WINDOW_SECONDS", 0.1),
        ):
            mock_settings.RATE_LIMIT_PER_USER = 1
            clear()
            assert is_rate_limited("user-1") is False
            assert is_rate_limited("user-1") is True
            time.sleep(0.15)
            # Window expired — should be allowed again
            assert is_rate_limited("user-1") is False


class TestDeleteCommand:
    """Test data deletion command detection."""

    def test_exact_match(self) -> None:
        """Exact deletion command is detected."""
        assert is_delete_command(DELETE_COMMAND) is True

    def test_with_whitespace(self) -> None:
        """Deletion command with surrounding whitespace is detected."""
        assert is_delete_command(f"  {DELETE_COMMAND}  ") is True

    def test_partial_match_rejected(self) -> None:
        """Partial deletion commands are rejected."""
        assert is_delete_command("刪除") is False
        assert is_delete_command("我的資料") is False

    def test_different_text_rejected(self) -> None:
        """Unrelated text is rejected."""
        assert is_delete_command("Metformin 是什麼？") is False
        assert is_delete_command("") is False


class TestConsentTracking:
    """Test PDPA consent tracking."""

    @pytest.mark.asyncio
    async def test_new_user_gets_consent_timestamp(self) -> None:
        """New users get consent_given_at set on creation."""
        from app.handlers.onboarding_handler import ensure_user_exists

        # Mock session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing user
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.refresh = AsyncMock()

        with patch("app.handlers.onboarding_handler.line_service"):
            await ensure_user_exists("U_new_user", mock_session)

        # Verify session.add was called with a user
        mock_session.add.assert_called_once()
        added_user = mock_session.add.call_args[0][0]
        assert added_user.consent_given_at is not None
        assert added_user.line_user_id == "U_new_user"

    @pytest.mark.asyncio
    async def test_existing_user_not_recreated(self) -> None:
        """Existing users are returned without creating a new record."""
        from app.handlers.onboarding_handler import ensure_user_exists

        existing_user = MagicMock()
        existing_user.line_user_id = "U_existing"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_session.execute = AsyncMock(return_value=mock_result)

        user = await ensure_user_exists("U_existing", mock_session)
        assert user == existing_user
        mock_session.add.assert_not_called()


class TestDataDeletion:
    """Test PDPA data deletion flow."""

    @pytest.mark.asyncio
    async def test_delete_existing_user(self) -> None:
        """Deleting an existing user removes their record."""
        from app.handlers.onboarding_handler import handle_data_deletion

        existing_user = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.handlers.onboarding_handler.line_service") as mock_line:
            mock_line.push_text = AsyncMock()
            result = await handle_data_deletion("U1234", mock_session)

        assert result is True
        mock_session.delete.assert_called_once_with(existing_user)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user(self) -> None:
        """Deleting a non-existent user returns False."""
        from app.handlers.onboarding_handler import handle_data_deletion

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.handlers.onboarding_handler.line_service") as mock_line:
            mock_line.push_text = AsyncMock()
            result = await handle_data_deletion("U_unknown", mock_session)

        assert result is False
        mock_session.delete.assert_not_called()


class TestMedicalSafetyGuardrails:
    """Test that DSPy signatures enforce medical safety rules."""

    def test_medication_explanation_never_recommends_dosage(self) -> None:
        """MedicationExplanation docstring enforces no dosage advice."""
        from app.services.dspy_service import MedicationExplanation

        docstring = MedicationExplanation.__doc__ or ""
        assert "NEVER give specific medical advice" in docstring
        assert "NEVER recommend dosage changes" in docstring

    def test_adherence_checkin_never_scolds(self) -> None:
        """AdherenceCheckIn docstring enforces non-judgmental tone."""
        from app.services.dspy_service import AdherenceCheckIn

        docstring = AdherenceCheckIn.__doc__ or ""
        assert "NEVER scold" in docstring
        assert "NEVER recommend catching up" in docstring

    def test_interaction_explanation_defers_to_doctor(self) -> None:
        """InteractionExplanation docstring defers to doctor."""
        from app.services.dspy_service import InteractionExplanation

        docstring = InteractionExplanation.__doc__ or ""
        assert "do NOT add medical judgement" in docstring
        assert "請在下次看醫生時告訴他" in docstring
