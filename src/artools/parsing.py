"""Shared parsing helpers for presentation adapters."""

from __future__ import annotations

from datetime import datetime, timezone


UTC = timezone.utc


class InputParseError(ValueError):
    """Raised when a presentation-layer value cannot be parsed."""


def parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC.

    Timezone-free values are interpreted as UTC for compatibility with the CLI
    behavior established in Step 8.
    """
    if not isinstance(value, str):
        raise TypeError("Timestamp must be a string")
    text = value.strip()
    if not text:
        raise InputParseError("Start time must not be empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise InputParseError(
            f"Invalid start time {value!r}; expected an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["InputParseError", "parse_utc_datetime"]
