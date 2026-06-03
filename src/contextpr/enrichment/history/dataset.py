from __future__ import annotations

from pathlib import Path

import pandas as pd

from contextpr.data.dataset import TARGET_COLUMN, load_dataset
from contextpr.enrichment.history.constants import MIN_RETRIEVAL_SCORE, STRONG_MATCH_SCORE
from contextpr.enrichment.history.types import IssueContextEvidence
from contextpr.enrichment.history.utils import (
    component_path,
    distribution,
    dominant_share,
    distribution_share,
    message_overlap,
    path_family,
    path_scope,
    salient_terms,
    share,
    token_overlap,
)
from contextpr.models import SonarIssue


class GlobalDatasetHistoryRetriever:
    def __init__(self, dataset_path: Path) -> None:
        self._dataset_path = dataset_path
        self._dataset: pd.DataFrame | None = None

    @property
    def is_available(self) -> bool:
        return self._dataset_path.is_file()

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        if not self.is_available:
            return None

        dataset = self._load_dataset()
        if dataset.empty:
            return None

        scored = dataset.assign(
            retrieval_score=dataset.apply(lambda row: self._score_row(issue, row), axis=1)
        )
        scored = scored[scored["retrieval_score"] >= MIN_RETRIEVAL_SCORE]
        if scored.empty:
            return None

        sort_columns = ["retrieval_score"]
        ascending = [False]
        if "creation_date" in scored.columns:
            sort_columns.append("creation_date")
            ascending.append(False)
        similar = scored.sort_values(
            by=sort_columns,
            ascending=ascending,
            na_position="last",
        ).head(top_k)

        return self._summarize_matches(issue, similar)

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

    def _summarize_matches(self, issue: SonarIssue, similar: pd.DataFrame) -> IssueContextEvidence:
        issue_scope = path_scope(issue.location.path)
        issue_family = path_family(issue.location.path)
        issue_path = issue.location.path
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        for _, row in similar.iterrows():
            record_path = component_path(str(row.get("component", "")))
            if path_scope(record_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and path_family(record_path) == issue_family:
                same_path_family_matches += 1
            if record_path == issue_path:
                same_exact_path_matches += 1

        sample_size = len(similar)
        same_rule_matches = int((similar["rule"] == issue.rule).sum())
        strong_match_count = int((similar["retrieval_score"] >= STRONG_MATCH_SCORE).sum())
        maintenance_distribution = distribution(
            self._maintenance_bucket(str(label))
            for label in similar[TARGET_COLUMN]
        )
        dominant_maintenance, dominant_maintenance_share = dominant_share(
            maintenance_distribution,
            sample_size=len(similar),
        )
        disposition_distribution = distribution(
            disposition
            for disposition in (
                self._disposition_bucket(row) for _, row in similar.iterrows()
            )
            if disposition is not None
        )
        dominant_disposition, dominant_disposition_share = dominant_share(
            disposition_distribution,
            sample_size=sum(count for _, count in disposition_distribution),
        )
        issue_salient_terms = salient_terms(
            issue,
            [f"{str(row.get('message', ''))} {str(row.get('component', ''))}" for _, row in similar.iterrows()],
        )

        return IssueContextEvidence(
            sample_size=sample_size,
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=share(same_rule_matches, sample_size),
            same_path_family_share=share(same_path_family_matches, sample_size),
            same_exact_path_share=share(same_exact_path_matches, sample_size),
            dominant_disposition=dominant_disposition,
            dominant_disposition_share=dominant_disposition_share,
            disposition_distribution=disposition_distribution,
            salient_terms=issue_salient_terms,
            resolved_share=distribution_share(disposition_distribution, "resolved"),
            accepted_share=distribution_share(disposition_distribution, "accepted"),
            persistent_share=distribution_share(disposition_distribution, "persistent"),
        )

    def _score_row(self, issue: SonarIssue, row: pd.Series) -> float:
        score = (
            6.0 * self._rule_similarity(issue, row)
            + 4.0 * self._code_similarity(issue, row)
            + 4.0 * self._location_similarity(issue, row)
        )
        if self._disposition_bucket(row) is not None:
            score += 1.0
        if str(row.get(TARGET_COLUMN, "")).strip():
            score += 0.5
        return round(score, 4)

    @staticmethod
    def _rule_similarity(issue: SonarIssue, row: pd.Series) -> float:
        if str(row.get("rule", "")) == issue.rule:
            return 1.0
        issue_tags = set(issue.tags)
        row_tags = {str(tag) for tag in row.get("tags", []) if isinstance(tag, str)}
        if issue_tags and issue_tags & row_tags:
            return 0.7
        if str(row.get("clean_code_attribute_category", "")) == issue.clean_code_attribute_category:
            return 0.7
        if str(row.get("clean_code_attribute", "")) == issue.clean_code_attribute:
            return 0.6
        if str(row.get("type", "")) == issue.issue_type and issue.issue_type:
            return 0.4
        return 0.0

    @staticmethod
    def _code_similarity(issue: SonarIssue, row: pd.Series) -> float:
        similarity = message_overlap(issue.message, str(row.get("message", "")))
        metadata_similarity = 0.0
        if str(row.get("type", "")) == issue.issue_type and issue.issue_type:
            metadata_similarity += 0.4
        if str(row.get("severity", "")) == issue.severity and issue.severity:
            metadata_similarity += 0.2
        row_tags = {str(tag) for tag in row.get("tags", []) if isinstance(tag, str)}
        if set(issue.tags) & row_tags:
            metadata_similarity += 0.2
        if str(row.get("clean_code_attribute", "")) == issue.clean_code_attribute:
            metadata_similarity += 0.1
        if str(row.get("clean_code_attribute_category", "")) == issue.clean_code_attribute_category:
            metadata_similarity += 0.1
        return round((0.7 * similarity) + (0.3 * min(metadata_similarity, 1.0)), 4)

    @staticmethod
    def _location_similarity(issue: SonarIssue, row: pd.Series) -> float:
        record_path = component_path(str(row.get("component", "")))
        issue_path = issue.location.path
        if record_path == issue_path and issue_path:
            return 1.0
        if path_family(record_path) == path_family(issue_path):
            return 0.7
        if path_scope(record_path) == path_scope(issue_path):
            return 0.4
        return 0.2 * token_overlap(issue_path, record_path)

    @staticmethod
    def _maintenance_bucket(label: str) -> str:
        normalized = label.strip().lower()
        if normalized in {"fix", "bugfix"}:
            return "behavior"
        if normalized in {"docs", "test", "build"}:
            return "supporting"
        return "cleanup"

    @staticmethod
    def _disposition_bucket(row: pd.Series) -> str | None:
        status = str(row.get("status", "")).strip().lower()
        resolution = str(row.get("resolution", "")).strip().lower()
        classification = str(row.get(TARGET_COLUMN, "")).strip().lower()
        if resolution in {"fixed", "resolved"} or status in {"closed", "resolved"}:
            return "resolved"
        if resolution in {"wontfix", "accepted"}:
            return "accepted"
        if status in {"open", "reopened"}:
            return "persistent"
        if classification in {"fix", "cleanup", "refactor"}:
            return "resolved"
        return None


IssueHistoryRetriever = GlobalDatasetHistoryRetriever
