"""LINE Messaging API service — send/receive helpers.

Handles signature validation, message sending (text, audio),
and audio content download from LINE CDN.
"""

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"


def validate_signature(body: bytes, signature: str) -> bool:
    """Validate LINE webhook signature.

    Args:
        body: Raw request body bytes.
        signature: X-Line-Signature header value.

    Returns:
        True if signature is valid.
    """
    hash_digest = hmac.new(
        settings.LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _auth_headers() -> dict[str, str]:
    """Get LINE API authorization headers."""
    return {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}


async def reply_text(reply_token: str, text: str) -> None:
    """Send a text reply using the reply token (single-use, <1 min expiry).

    Args:
        reply_token: LINE reply token from the webhook event.
        text: Text message to send.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LINE_API_BASE}/message/reply",
            headers=_auth_headers(),
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": text}],
            },
        )
        if response.status_code != 200:
            logger.warning(
                "LINE reply failed: status=%d body=%s",
                response.status_code,
                response.text,
            )


async def push_text(user_id: str, text: str) -> None:
    """Send a text push message to a user.

    Args:
        user_id: LINE user ID.
        text: Text message to send.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_auth_headers(),
            json={
                "to": user_id,
                "messages": [{"type": "text", "text": text}],
            },
        )
        if response.status_code != 200:
            logger.warning(
                "LINE push failed: status=%d body=%s",
                response.status_code,
                response.text,
            )


async def push_audio(user_id: str, audio_url: str, duration_ms: int) -> None:
    """Send an audio push message to a user.

    Note: LINE requires audio to be hosted at a public HTTPS URL.
    For prototype, we upload to a temporary storage or use a data URI workaround.

    Args:
        user_id: LINE user ID.
        audio_url: Public HTTPS URL of the audio file.
        duration_ms: Duration of audio in milliseconds.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_auth_headers(),
            json={
                "to": user_id,
                "messages": [
                    {
                        "type": "audio",
                        "originalContentUrl": audio_url,
                        "duration": duration_ms,
                    }
                ],
            },
        )
        if response.status_code != 200:
            logger.warning(
                "LINE audio push failed: status=%d body=%s",
                response.status_code,
                response.text,
            )


async def download_content(message_id: str) -> bytes:
    """Download content (audio, image, etc.) from LINE CDN.

    Args:
        message_id: LINE message ID.

    Returns:
        Content bytes.

    Raises:
        httpx.HTTPStatusError: If download fails.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{LINE_DATA_API_BASE}/message/{message_id}/content",
            headers=_auth_headers(),
        )
        response.raise_for_status()
        return response.content


def parse_webhook_events(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse webhook body into a list of events.

    Args:
        body: Parsed JSON webhook body.

    Returns:
        List of event dictionaries.
    """
    return body.get("events", [])
