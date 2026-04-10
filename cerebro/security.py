"""Fast redaction helpers for vault-bound and synthesis-bound text."""

import re
from typing import Final

_PATTERN_EMAIL: Final = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
_PATTERN_CARD: Final = re.compile(
    r"\b(?:"
    r"4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}|"
    r"5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}|"
    r"3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}|"
    r"6(?:011|5\d{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}|"
    r"(?:\d{4}[\s-]?){3}\d{4}"
    r")\b",
)
_PATTERN_IPV4: Final = re.compile(
    r"(?<![0-9])(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?![0-9])",
)
_PATTERN_SK: Final = re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b", re.IGNORECASE)
_PATTERN_KEY_PREFIX: Final = re.compile(
    r"\bkey-[a-zA-Z0-9_-]{8,}\b", re.IGNORECASE
)
_PATTERN_HEX_LONG: Final = re.compile(r"\b[a-fA-F0-9]{32,}\b")


def scrub_sensitive_data(text: str) -> str:
    """Redact common PII and secret-shaped strings using linear-time regex passes.

    Patterns are compiled once at import to keep hot-path overhead minimal.
    Order is chosen so card-like digit runs are handled before IPv4 to reduce
    ambiguous matches on numeric-heavy inputs.

    Args:
        text: Raw user or model-generated content.

    Returns:
        Same string with sensitive spans replaced by fixed redaction tokens.

    Raises:
        None.
    """
    if not text:
        return text
    s = _PATTERN_EMAIL.sub("[EMAIL_REDACTED]", text)
    s = _PATTERN_CARD.sub("[CARD_REDACTED]", s)
    s = _PATTERN_IPV4.sub("[IP_REDACTED]", s)
    s = _PATTERN_SK.sub("[API_KEY_REDACTED]", s)
    s = _PATTERN_KEY_PREFIX.sub("[API_KEY_REDACTED]", s)
    s = _PATTERN_HEX_LONG.sub("[API_KEY_REDACTED]", s)
    return s
