from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from contextpr.models import SonarIssue
from ml.dataset import load_dataset

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
TEST_PATH_TOKENS = {"test", "tests", "spec", "specs"}
MIN_RETRIEVAL_SCORE = 4.0
STRONG_MATCH_SCORE = 10.0

DISPOSITION_LABELS = {
    "resolved": "resolved in code",
    "accepted": "kept as accepted debt",
    "persistent": "left open or deferred",
}

MAINTENANCE_LABELS = {
    "cleanup": "small refactors",
    "behavior": "behavior-sensitive changes",
    "supporting": "nearby follow-up changes",
}


@dataclass(frozen=True, slots=True)
class HistoricalContext:
    sample_size: int
    same_rule_matches: int
    same_scope_matches: int
    same_path_family_matches: int
    strong_match_count: int
    dominant_maintenance: str | None
    dominant_maintenance_share: float
    maintenance_distribution: tuple[tuple[str, int], ...]
    dominant_disposition: str | None = None
    dominant_disposition_share: float = 0.0
    disposition_distribution: tuple[tuple[str, int], ...] = ()


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
        scored = scored[scored["retrieval_score"] >= MIN_RETRIEVAL_SCORE]
        scored = self._sort_scored_matches(scored)
        if scored.empty:
            return None

        similar = scored.head(top_k)
        maintenance_distribution = self._distribution(
            self._maintenance_bucket(str(label))
            for label in similar["ccs_classification"]
        )
        dominant_maintenance, dominant_maintenance_share = self._dominant_share(
            maintenance_distribution,
            sample_size=len(similar),
        )
        disposition_distribution = self._distribution(
            disposition
            for disposition in (
                self._disposition_bucket(row) for _, row in similar.iterrows()
            )
            if disposition is not None
        )
        dominant_disposition, dominant_disposition_share = self._dominant_share(
            disposition_distribution,
            sample_size=sum(count for _, count in disposition_distribution),
        )

        issue_scope = self._path_scope(issue.location.path)
        issue_family = self._path_family(issue.location.path)
        same_scope_matches = 0
        same_path_family_matches = 0
        for _, row in similar.iterrows():
            component_path = self._component_path(str(row.get("component", "")))
            if self._path_scope(component_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and self._path_family(component_path) == issue_family:
                same_path_family_matches += 1

        return HistoricalContext(
            sample_size=len(similar),
            same_rule_matches=int((similar["rule"] == issue.rule).sum()),
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            strong_match_count=int((similar["retrieval_score"] >= STRONG_MATCH_SCORE).sum()),
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            dominant_disposition=dominant_disposition,
            dominant_disposition_share=dominant_disposition_share,
            disposition_distribution=disposition_distribution,
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
    def _sort_scored_matches(scored: pd.DataFrame) -> pd.DataFrame:
        sort_columns = ["retrieval_score"]
        ascending = [False]
        if "creation_date" in scored.columns:
            sort_columns.append("creation_date")
            ascending.append(False)

        return scored.sort_values(
            by=sort_columns,
            ascending=ascending,
            na_position="last",
        )

    @staticmethod
    def _distribution(values: list[str] | tuple[str, ...] | pd.Series | object) -> tuple[tuple[str, int], ...]:
        counts = Counter(str(value) for value in values if str(value))
        return tuple(counts.most_common())

    @staticmethod
    def _dominant_share(
        distribution: tuple[tuple[str, int], ...],
        *,
        sample_size: int,
    ) -> tuple[str | None, float]:
        if not distribution or sample_size <= 0:
            return None, 0.0

        label, count = distribution[0]
        return label, round(count / sample_size, 4)

    @staticmethod
    def _score_row(issue: SonarIssue, row: pd.Series) -> float:
        score = 0.0

        row_rule = str(row.get("rule", ""))
        row_component = str(row.get("component", ""))
        row_path = IssueHistoryRetriever._component_path(row_component)
        issue_path = issue.location.path

        if row_rule == issue.rule:
            score += 7.0
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
            score += 1.5
        if str(row.get("severity", "")) == issue.severity and issue.severity:
            score += 1.5
        if str(row.get("file_extension", "")) == (
            Path(issue_path).suffix.lower() or "no_extension"
        ):
            score += 1.0

        issue_tags = set(issue.tags)
        row_tags = {str(tag) for tag in row.get("tags", [])}
        score += float(len(issue_tags & row_tags))

        if IssueHistoryRetriever._path_scope(row_path) == IssueHistoryRetriever._path_scope(issue_path):
            score += 1.5
        if IssueHistoryRetriever._path_family(row_path) == IssueHistoryRetriever._path_family(issue_path):
            score += 2.5

        score += 3.0 * IssueHistoryRetriever._token_overlap(issue_path, row_path)
        score += 4.0 * IssueHistoryRetriever._message_overlap(
            issue.message,
            str(row.get("message", "")),
        )
        score += IssueHistoryRetriever._utility_score(row)
        return score

    @staticmethod
    def _utility_score(row: pd.Series) -> float:
        score = 0.5
        if str(row.get("ccs_classification", "")).strip():
            score += 1.0
        if IssueHistoryRetriever._disposition_bucket(row) is not None:
            score += 1.5
        return score

    @staticmethod
    def _maintenance_bucket(label: str) -> str:
        normalized = label.strip().lower()
        if normalized in {"fix", "feat", "perf"}:
            return "behavior"
        if normalized in {"docs", "test", "build", "ci"}:
            return "supporting"
        return "cleanup"

    @staticmethod
    def _disposition_bucket(row: pd.Series) -> str | None:
        for column in (
            "resolution",
            "issue_resolution",
            "status",
            "issue_status",
            "review_status",
        ):
            value = str(row.get(column, "")).strip().lower()
            if not value:
                continue
            if value in {"fixed", "resolved", "closed"}:
                return "resolved"
            if value in {"wontfix", "won't fix", "false positive", "accepted", "acknowledged"}:
                return "accepted"
            if value in {"open", "confirmed", "reopened", "persisted", "unresolved"}:
                return "persistent"
        return None

    @staticmethod
    def _component_path(component: str) -> str:
        if ":" in component:
            return component.split(":", maxsplit=1)[1]
        return component

    @staticmethod
    def _path_scope(path: str) -> str:
        tokens = set(IssueHistoryRetriever._tokens(path))
        return "test" if tokens & TEST_PATH_TOKENS else "production"

    @staticmethod
    def _path_family(path: str) -> str:
        parts = [part for part in Path(path).parts if part not in {"", "."}]
        if not parts:
            return ""
        return "/".join(parts[:2]).lower()

    @staticmethod
    def _tokens(value: str) -> tuple[str, ...]:
        return tuple(TOKEN_PATTERN.findall(value.lower()))

    @staticmethod
    def _token_overlap(left: str, right: str) -> float:
        left_tokens = set(IssueHistoryRetriever._tokens(left))
        right_tokens = set(IssueHistoryRetriever._tokens(right))
        if not left_tokens or not right_tokens:
            return 0.0

        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union

    @staticmethod
    def _message_overlap(left: str, right: str) -> float:
        return IssueHistoryRetriever._token_overlap(left, right)
