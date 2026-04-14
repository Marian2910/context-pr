from __future__ import annotations

import ast
import json
from pathlib import PurePosixPath
from typing import Any


def parse_tags(value: object) -> list[str]:
    """Normalize tag values into a list of strings."""
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]

    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    parsed = _parse_serialized_value(text)
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in text.split(",") if item.strip()]


def extract_severity(value: object) -> str:
    """Extract a severity value from the impacts payload."""
    parsed = _coerce_to_sequence(value)
    for item in parsed:
        if isinstance(item, dict):
            severity = item.get("severity")
            if isinstance(severity, str) and severity.strip():
                return severity.strip().upper()

    return "UNKNOWN"


def extract_file_extension(component: object) -> str:
    """Extract a normalized file extension from a Sonar component path."""
    if not isinstance(component, str) or not component.strip():
        return "unknown"

    component_path = component.split(":", maxsplit=1)[-1]
    suffix = PurePosixPath(component_path).suffix.lower()
    return suffix or "no_extension"


def _coerce_to_sequence(value: object) -> list[Any]:
    """Coerce serialized list-like values into a Python list."""
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple | set):
        return list(value)

    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    parsed = _parse_serialized_value(text)
    return parsed if isinstance(parsed, list) else []


def _parse_serialized_value(value: str) -> object:
    """Parse JSON- or Python-literal-like strings safely."""
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(value)
        except (json.JSONDecodeError, SyntaxError, ValueError):
            continue

    return value
