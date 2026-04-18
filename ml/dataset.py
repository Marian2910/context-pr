from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from ml.utils import extract_file_extension, extract_severity, parse_tags

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
    normalized["tags"] = normalized["tags"].apply(parse_tags)
    normalized["severity"] = normalized["impacts"].apply(extract_severity)
    normalized["file_extension"] = normalized["component"].apply(extract_file_extension)
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
