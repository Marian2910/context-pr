from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

import pandas as pd

TARGET_COLUMN = "ccs_classification"
REQUIRED_COLUMNS = (
    "message",
    "rule",
    "type",
    "tags",
    "clean_code_attribute",
    "clean_code_attribute_category",
    "impacts",
    "component",
    TARGET_COLUMN,
)


def load_dataset(df: pd.DataFrame) -> pd.DataFrame:
    _validate_columns(df.columns)

    normalized = df.copy()
    normalized["tags"] = normalized["tags"].apply(_parse_tags)
    normalized["severity"] = normalized["impacts"].apply(_extract_severity)
    normalized["file_extension"] = normalized["component"].apply(_extract_file_extension)
    normalized[TARGET_COLUMN] = normalized[TARGET_COLUMN].apply(_normalize_text)

    for column in (
        "message",
        "rule",
        "type",
        "clean_code_attribute",
        "clean_code_attribute_category",
        "component",
    ):
        normalized[column] = normalized[column].apply(_normalize_text)

    normalized = normalized[normalized[TARGET_COLUMN] != ""].reset_index(drop=True)
    return normalized


def _validate_columns(columns: Iterable[object]) -> None:
    missing = sorted(set(REQUIRED_COLUMNS) - {str(column) for column in columns})
    if missing:
        formatted = ", ".join(missing)
        raise ValueError(f"Dataset is missing required columns: {formatted}")


def _normalize_text(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value).strip()


def _parse_tags(value: object) -> list[str]:
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


def _extract_severity(value: object) -> str:
    parsed = _coerce_to_sequence(value)
    for item in parsed:
        if isinstance(item, dict):
            severity = item.get("severity")
            if isinstance(severity, str) and severity.strip():
                return severity.strip().upper()

    return "UNKNOWN"


def _extract_file_extension(component: object) -> str:
    if not isinstance(component, str) or not component.strip():
        return "unknown"

    component_path = component.split(":", maxsplit=1)[-1]
    suffix = PurePosixPath(component_path).suffix.lower()
    return suffix or "no_extension"


def _coerce_to_sequence(value: object) -> list[Any]:
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
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(value)
        except (SyntaxError, ValueError):
            continue

    return value
