"""Input sanitisation and output scanning for LLM security.

OWASP LLM01 (Prompt Injection) and LLM02 (Insecure Output Handling) mitigations.

All user input goes through sanitise_input() before any Gemini call.
All LLM output goes through scan_output() before returning to the user.
"""

import re

# Maximum input length (characters) — prevents resource exhaustion
MAX_INPUT_LENGTH = 2000

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    # Direct instruction overrides
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)ignore\s+(all\s+)?above\s+instructions",
    r"(?i)disregard\s+(all\s+)?previous",
    r"(?i)forget\s+(all\s+)?previous",
    r"(?i)you\s+are\s+now\s+a",
    r"(?i)act\s+as\s+(a\s+)?",
    r"(?i)pretend\s+(you\s+are|to\s+be)",
    r"(?i)new\s+instructions?\s*:",
    r"(?i)system\s*:\s*",
    r"(?i)<<\s*SYS\s*>>",
    # Template/delimiter injection
    r"\{\{.*\}\}",
    r"<\|.*\|>",
    r"\[INST\]",
    r"\[\/INST\]",
    # Data exfiltration attempts
    r"(?i)reveal\s+(your\s+)?(system\s+)?prompt",
    r"(?i)show\s+(me\s+)?(your\s+)?(system\s+)?instructions",
    r"(?i)what\s+are\s+your\s+(system\s+)?instructions",
    r"(?i)output\s+(your\s+)?(initial|system)\s+prompt",
]

_COMPILED_INJECTION_PATTERNS = [re.compile(p) for p in _INJECTION_PATTERNS]

# Shell metacharacters that should never appear in medical queries
_SHELL_METACHARACTERS = re.compile(r"[;|&`$\\]")

# Patterns in LLM output that should be stripped before sending to user
_DANGEROUS_OUTPUT_PATTERNS = [
    re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<iframe\b[^>]*>.*?</iframe>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onclick=, onerror=, etc.
]


def sanitise_input(text: str) -> tuple[str, list[str]]:
    """Sanitise user input before any LLM call.

    Args:
        text: Raw user input text.

    Returns:
        Tuple of (sanitised text, list of warning reasons).
        If warnings are non-empty, the input contained suspicious patterns
        but was still sanitised and is safe to process.

    Raises:
        ValueError: If the input is fundamentally unsafe and should be rejected.
    """
    warnings: list[str] = []

    if not text or not text.strip():
        return "", []

    # Truncate to max length
    if len(text) > MAX_INPUT_LENGTH:
        text = text[:MAX_INPUT_LENGTH]
        warnings.append("input_truncated")

    # Strip shell metacharacters
    cleaned = _SHELL_METACHARACTERS.sub("", text)
    if cleaned != text:
        warnings.append("shell_chars_removed")
        text = cleaned

    # Check for injection patterns
    for pattern in _COMPILED_INJECTION_PATTERNS:
        if pattern.search(text):
            warnings.append("injection_pattern_detected")
            # Don't reject — strip the pattern and continue
            text = pattern.sub("", text)

    # Strip excessive whitespace
    text = " ".join(text.split())

    return text.strip(), warnings


def scan_output(text: str) -> str:
    """Scan LLM output for dangerous content before sending to user.

    Args:
        text: Raw LLM output text.

    Returns:
        Sanitised output safe for LINE message delivery.
    """
    if not text:
        return ""

    # Strip dangerous HTML/script patterns
    for pattern in _DANGEROUS_OUTPUT_PATTERNS:
        text = pattern.sub("", text)

    # Strip any remaining HTML tags (LINE renders plain text only)
    text = re.sub(r"<[^>]+>", "", text)

    return text.strip()
