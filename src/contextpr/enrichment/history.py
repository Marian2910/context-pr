from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from contextpr.models import SonarIssue
from ml.dataset import load_dataset

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class HistoricalContext:

    sample_size: int
    label_distribution: tuple[tuple[str, int], ...]
    same_rule_matches: int


class IssueHistoryRetriever:

    def __init__(self, dataset_path: Path) -> None:
        self._dataset_path = dataset_path
        self._dataset: pd.DataFrame | None = None

    @property
    def is_available(self) -> bool:
        return self._dataset_path.is_file()

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> HistoricalContext | None:
        if not self.is_available:
            return None

        dataset = self._load_dataset()
        if dataset.empty:
            return None

        scored = dataset.assign(
            retrieval_score=dataset.apply(lambda row: self._score_row(issue, row), axis=1)
        )
        scored = scored[scored["retrieval_score"] > 0].sort_values(
            by=["retrieval_score", "creation_date"],
            ascending=[False, False],
            na_position="last",
        )
        if scored.empty:
            return None

        similar = scored.head(top_k)
        distribution = Counter(str(label) for label in similar["ccs_classification"])
        same_rule_matches = int((similar["rule"] == issue.rule).sum())
        return HistoricalContext(
            sample_size=len(similar),
            label_distribution=tuple(distribution.most_common(3)),
            same_rule_matches=same_rule_matches,
        )

    def _load_dataset(self) -> pd.DataFrame:
        if self._dataset is None:
            frame = self._read_frame()
            self._dataset = load_dataset(frame)
        return self._dataset

    def _read_frame(self) -> pd.DataFrame:
        suffix = self._dataset_path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(self._dataset_path)
        if suffix == ".csv":
            return pd.read_csv(self._dataset_path)
        raise ValueError(f"Unsupported dataset format: {self._dataset_path}")

    @staticmethod
    def _score_row(issue: SonarIssue, row: pd.Series) -> float:
        score = 0.0

        if str(row.get("rule", "")) == issue.rule:
            score += 5.0
        if str(row.get("type", "")) == issue.issue_type and issue.issue_type:
            score += 2.5
        if (
            str(row.get("clean_code_attribute", "")) == issue.clean_code_attribute
            and issue.clean_code_attribute
        ):
            score += 2.0
        if (
            str(row.get("clean_code_attribute_category", ""))
            == issue.clean_code_attribute_category
            and issue.clean_code_attribute_category
        ):
            score += 2.0
        if str(row.get("severity", "")) == issue.severity and issue.severity:
            score += 1.5
        if str(row.get("file_extension", "")) == (
            Path(issue.location.path).suffix.lower() or "no_extension"
        ):
            score += 1.0

        issue_tags = set(issue.tags)
        row_tags = {str(tag) for tag in row.get("tags", [])}
        score += float(len(issue_tags & row_tags))
        score += 4.0 * IssueHistoryRetriever._message_overlap(
            issue.message,
            str(row.get("message", "")),
        )
        return score

    @staticmethod
    def _message_overlap(left: str, right: str) -> float:
        left_tokens = set(TOKEN_PATTERN.findall(left.lower()))
        right_tokens = set(TOKEN_PATTERN.findall(right.lower()))
        if not left_tokens or not right_tokens:
            return 0.0

        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union
