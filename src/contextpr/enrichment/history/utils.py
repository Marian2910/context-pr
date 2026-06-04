from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from contextpr.enrichment.history.constants import STOP_TOKENS, TEST_PATH_TOKENS, TOKEN_PATTERN
from contextpr.models import SonarIssue


def distribution(values: Iterable[object]) -> tuple[tuple[str, int], ...]:
    counts = Counter(str(value) for value in values if str(value))
    return tuple(counts.most_common())


def dominant_share(
    items: tuple[tuple[str, int], ...],
    *,
    sample_size: int,
) -> tuple[str | None, float]:
    if not items or sample_size <= 0:
        return None, 0.0
    label, count = items[0]
    return label, round(count / sample_size, 4)


def share(count: int, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.0
    return round(count / sample_size, 4)


def distribution_share(
    items: tuple[tuple[str, int], ...],
    label: str,
) -> float:
    total = sum(count for _, count in items)
    if total <= 0:
        return 0.0
    for current_label, count in items:
        if current_label == label:
            return round(count / total, 4)
    return 0.0


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


def salient_terms(
    issue: SonarIssue,
    documents: list[str],
    *,
    top_k: int = 3,
) -> tuple[str, ...]:
    issue_terms = set(
        content_tokens(issue.message) + content_tokens(issue.location.path) + tuple(issue.tags)
    )
    if not issue_terms or not documents:
        return ()

    document_terms = [set(content_tokens(document)) for document in documents]
    if not any(document_terms):
        return ()

    scores: list[tuple[str, float]] = []
    document_count = len(document_terms)
    for term in sorted(issue_terms):
        document_frequency = sum(1 for terms in document_terms if term in terms)
        if document_frequency == 0:
            continue
        term_frequency = sum(content_tokens(document).count(term) for document in documents)
        idf = math.log((1 + document_count) / (1 + document_frequency)) + 1.0
        scores.append((term, term_frequency * idf))

    scores.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return tuple(term for term, _score in scores[:top_k])


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
