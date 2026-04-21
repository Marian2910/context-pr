import pytest

from contextpr.utils.text import normalize_whitespace, truncate_text


def test_normalize_whitespace_collapses_repeated_spaces() -> None:
    assert normalize_whitespace("  one\n two\tthree  ") == "one two three"


def test_truncate_text_returns_normalized_text_when_under_limit() -> None:
    assert truncate_text("  short   text  ", 20) == "short text"


def test_truncate_text_shortens_long_text_with_ellipsis() -> None:
    assert truncate_text("one two three four", 11) == "one two..."


def test_truncate_text_handles_tiny_limits() -> None:
    assert truncate_text("abcdef", 3) == "..."
    assert truncate_text("abcdef", 2) == ".."


def test_truncate_text_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be greater than zero"):
        truncate_text("text", 0)
