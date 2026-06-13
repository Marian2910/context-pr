from __future__ import annotations

from datetime import datetime
from pathlib import Path

from contextpr.enrichment.history.constants import STOP_TOKENS, TEST_PATH_TOKENS, TOKEN_PATTERN


def component_path(component: str) -> str:
    if ":" in component:
        return component.split(":", maxsplit=1)[1]
    return component


def path_scope(path: str) -> str:
    path_tokens = set(tokens(path))
    return "test" if path_tokens & TEST_PATH_TOKENS else "production"


def path_family(path: str) -> str:
    parts = [part for part in Path(path).parts if part not in {"", "."}]
    if not parts:
        return ""
    directory_parts = parts[:-1]
    if not directory_parts:
        return ""
    return "/".join(directory_parts[:2]).lower()


def tokens(value: str) -> tuple[str, ...]:
    return tuple(TOKEN_PATTERN.findall(value.lower()))


def token_overlap(left: str, right: str) -> float:
    left_tokens = set(tokens(left))
    right_tokens = set(tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union


def message_overlap(left: str, right: str) -> float:
    return token_overlap(left, right)


def content_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in tokens(value)
        if len(token) > 2 and token not in STOP_TOKENS and not token.isdigit()
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip()
    for candidate in (normalized, normalized.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass

    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    return None
