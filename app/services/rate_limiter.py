"""Per-user rate limiting for AI-heavy endpoints.

Limits requests per LINE user ID to prevent abuse and control API costs.
Uses an in-memory sliding window counter (sufficient for single-process prototype).
"""

import time
from collections import defaultdict

from app.config import settings

# Sliding window: user_id -> list of request timestamps
_request_log: dict[str, list[float]] = defaultdict(list)

# Window size in seconds
_WINDOW_SECONDS = 60


def is_rate_limited(user_id: str) -> bool:
    """Check if a user has exceeded the rate limit.

    Args:
        user_id: LINE user ID.

    Returns:
        True if the user is rate-limited and should be rejected.
    """
    now = time.monotonic()
    window_start = now - _WINDOW_SECONDS

    # Clean old entries
    _request_log[user_id] = [ts for ts in _request_log[user_id] if ts > window_start]

    if len(_request_log[user_id]) >= settings.RATE_LIMIT_PER_USER:
        return True

    _request_log[user_id].append(now)
    return False


def clear() -> None:
    """Clear all rate limit state. For testing."""
    _request_log.clear()
