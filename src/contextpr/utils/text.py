"""Text helper functions used across ContextPR."""

from __future__ import annotations


def normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace and trim the result."""
    return " ".join(value.split())


def truncate_text(value: str, limit: int) -> str:
    """Truncate text to a maximum width while preserving readability."""
    if limit < 1:
        raise ValueError("limit must be greater than zero")

    normalized = normalize_whitespace(value)
    if len(normalized) <= limit:
        return normalized

    if limit <= 3:
        return "." * limit

    return f"{normalized[: limit - 3].rstrip()}..."
