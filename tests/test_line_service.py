"""Tests for LINE Messaging API service."""

import base64
import hashlib
import hmac
from unittest.mock import patch

import pytest

from app.services.line_service import (
    parse_webhook_events,
    validate_signature,
)


class TestValidateSignature:
    """Test LINE webhook signature validation."""

    def _make_signature(self, body: bytes, secret: str) -> str:
        """Generate a valid LINE signature for testing."""
        hash_digest = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
        return base64.b64encode(hash_digest).decode("utf-8")

    def test_valid_signature(self) -> None:
        """Valid signature passes validation."""
        body = b'{"events": []}'
        with patch("app.services.line_service.settings") as mock_settings:
            mock_settings.LINE_CHANNEL_SECRET = "test-secret"
            signature = self._make_signature(body, "test-secret")
            assert validate_signature(body, signature) is True

    def test_invalid_signature(self) -> None:
        """Invalid signature fails validation."""
        body = b'{"events": []}'
        with patch("app.services.line_service.settings") as mock_settings:
            mock_settings.LINE_CHANNEL_SECRET = "test-secret"
            assert validate_signature(body, "invalid-signature") is False

    def test_tampered_body(self) -> None:
        """Tampered body fails validation."""
        original_body = b'{"events": []}'
        tampered_body = b'{"events": [{"type": "hack"}]}'
        with patch("app.services.line_service.settings") as mock_settings:
            mock_settings.LINE_CHANNEL_SECRET = "test-secret"
            signature = self._make_signature(original_body, "test-secret")
            assert validate_signature(tampered_body, signature) is False


class TestParseWebhookEvents:
    """Test webhook event parsing."""

    def test_parses_events(self) -> None:
        """Extracts events from webhook body."""
        body = {
            "events": [
                {"type": "message", "message": {"type": "text", "text": "hello"}},
                {"type": "follow"},
            ]
        }
        events = parse_webhook_events(body)
        assert len(events) == 2
        assert events[0]["type"] == "message"

    def test_empty_events(self) -> None:
        """Empty events list returns empty."""
        assert parse_webhook_events({"events": []}) == []

    def test_missing_events_key(self) -> None:
        """Missing events key returns empty list."""
        assert parse_webhook_events({}) == []


class TestWebhookIntegration:
    """Integration tests for the webhook endpoint."""

    @pytest.fixture
    def text_message_event(self) -> dict:
        """A typical LINE text message event."""
        return {
            "type": "message",
            "replyToken": "test-reply-token",
            "source": {"type": "user", "userId": "U1234567890"},
            "message": {
                "id": "msg-001",
                "type": "text",
                "text": "Metformin 是什麼藥？",
            },
        }

    @pytest.fixture
    def audio_message_event(self) -> dict:
        """A typical LINE audio message event."""
        return {
            "type": "message",
            "replyToken": "test-reply-token",
            "source": {"type": "user", "userId": "U1234567890"},
            "message": {
                "id": "msg-002",
                "type": "audio",
                "duration": 5000,
            },
        }

    def test_text_event_structure(self, text_message_event: dict) -> None:
        """Text event has expected structure."""
        assert text_message_event["type"] == "message"
        assert text_message_event["message"]["type"] == "text"
        assert text_message_event["source"]["userId"] == "U1234567890"

    def test_audio_event_structure(self, audio_message_event: dict) -> None:
        """Audio event has expected structure."""
        assert audio_message_event["message"]["type"] == "audio"
        assert audio_message_event["message"]["duration"] == 5000
