import pandas as pd
import pytest

from contextpr.data.dataset import (
    TARGET_COLUMN,
    _coerce_to_sequence,
    _extract_file_extension,
    _parse_tags,
    load_dataset,
    load_dataset_file,
)


def test_load_dataset_normalizes_runtime_fields() -> None:
    frame = pd.DataFrame(
        [
            {
                "message": "  Remove unused parameter  ",
                "rule": " python:S1172 ",
                "type": " CODE_SMELL ",
                "tags": "['unused', 'style']",
                "clean_code_attribute": " CLEAR ",
                "clean_code_attribute_category": " INTENTIONAL ",
                "impacts": "[{'severity': 'low'}]",
                "component": "repo:src/app.py",
                TARGET_COLUMN: " refactor ",
            },
            {
                "message": "Ignored because target is blank",
                "rule": "python:S1172",
                "type": "CODE_SMELL",
                "tags": "",
                "clean_code_attribute": "CLEAR",
                "clean_code_attribute_category": "INTENTIONAL",
                "impacts": "",
                "component": "repo:src/views",
                TARGET_COLUMN: "   ",
            },
        ]
    )

    normalized = load_dataset(frame)

    assert len(normalized) == 1
    row = normalized.iloc[0]
    assert row["message"] == "Remove unused parameter"
    assert row["rule"] == "python:S1172"
    assert row["type"] == "CODE_SMELL"
    assert row["tags"] == ["unused", "style"]
    assert row["severity"] == "LOW"
    assert row["file_extension"] == ".py"
    assert row[TARGET_COLUMN] == "refactor"


def test_load_dataset_handles_serialized_fallbacks_and_missing_values() -> None:
    frame = pd.DataFrame(
        [
            {
                "message": None,
                "rule": None,
                "type": None,
                "tags": "lint, cleanup",
                "clean_code_attribute": None,
                "clean_code_attribute_category": None,
                "impacts": "not-json",
                "component": "",
                TARGET_COLUMN: "cleanup",
            },
            {
                "message": "Tuple tags",
                "rule": "python:S100",
                "type": "CODE_SMELL",
                "tags": ("design", "review"),
                "clean_code_attribute": "CLEAR",
                "clean_code_attribute_category": "INTENTIONAL",
                "impacts": [{"severity": "medium"}],
                "component": None,
                TARGET_COLUMN: "docs",
            },
        ]
    )

    normalized = load_dataset(frame)

    first = normalized.iloc[0]
    second = normalized.iloc[1]
    assert first["message"] == ""
    assert first["rule"] == ""
    assert first["tags"] == ["lint", "cleanup"]
    assert first["severity"] == "UNKNOWN"
    assert first["file_extension"] == "unknown"
    assert second["tags"] == ["design", "review"]
    assert second["severity"] == "MEDIUM"
    assert second["file_extension"] == "unknown"


def test_load_dataset_requires_expected_columns() -> None:
    frame = pd.DataFrame([{"message": "missing almost everything"}])

    with pytest.raises(ValueError, match="Dataset is missing required columns"):
        load_dataset(frame)


def test_load_dataset_file_reads_csv(tmp_path) -> None:
    dataset_path = tmp_path / "issues.csv"
    pd.DataFrame(
        [
            {
                "message": "Remove unused parameter",
                "rule": "python:S1172",
                "type": "CODE_SMELL",
                "tags": "['unused']",
                "clean_code_attribute": "CLEAR",
                "clean_code_attribute_category": "INTENTIONAL",
                "impacts": "[{'severity': 'low'}]",
                "component": "repo:src/app.py",
                TARGET_COLUMN: "fix",
            }
        ]
    ).to_csv(dataset_path, index=False)

    normalized = load_dataset_file(dataset_path)

    assert len(normalized) == 1
    assert normalized.iloc[0]["severity"] == "LOW"


def test_load_dataset_file_reads_excel(tmp_path) -> None:
    dataset_path = tmp_path / "issues.xlsx"
    pd.DataFrame(
        [
            {
                "message": "Remove unused parameter",
                "rule": "python:S1172",
                "type": "CODE_SMELL",
                "tags": "['unused']",
                "clean_code_attribute": "CLEAR",
                "clean_code_attribute_category": "INTENTIONAL",
                "impacts": "[{'severity': 'low'}]",
                "component": "repo:src/app.py",
                TARGET_COLUMN: "fix",
            }
        ]
    ).to_excel(dataset_path, index=False)

    normalized = load_dataset_file(dataset_path)

    assert len(normalized) == 1
    assert normalized.iloc[0]["file_extension"] == ".py"


def test_load_dataset_file_rejects_unknown_format(tmp_path) -> None:
    dataset_path = tmp_path / "issues.txt"
    dataset_path.write_text("not a dataset", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported dataset format"):
        load_dataset_file(dataset_path)


def test_parse_tags_and_helpers_cover_non_default_branches() -> None:
    assert _parse_tags({"not": "supported"}) == []
    assert _parse_tags("{'solo': 'value'}") == ["{'solo': 'value'}"]
    assert _coerce_to_sequence({"bad": "type"}) == []
    assert _coerce_to_sequence(" {'severity': 'low'} ") == []
    assert _extract_file_extension("repo:Makefile") == "no_extension"
