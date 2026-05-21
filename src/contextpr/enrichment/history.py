from __future__ import annotations

import json
import logging
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from contextpr.data.dataset import load_dataset
from contextpr.enrichment.history_constants import (
    DISPOSITION_LABELS,
    MAINTENANCE_LABELS,
    MIN_RETRIEVAL_SCORE,
    STOP_TOKENS,
    STRONG_MATCH_SCORE,
    TEST_PATH_TOKENS,
    TOKEN_PATTERN,
)
from contextpr.models import SonarIssue
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    SonarIssueRecord,
)

fix_reference_debug_logger = logging.getLogger("contextpr.fix_reference_debug")


@dataclass(frozen=True, slots=True)
class HistoricalFixReference:
    pr_number: int
    pr_title: str
    pr_url: str
    file_url: str | None
    file_path: str
    resolved_at: str
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueContextEvidence:
    sample_size: int
    same_rule_matches: int
    same_scope_matches: int
    same_path_family_matches: int
    strong_match_count: int
    dominant_maintenance: str | None
    dominant_maintenance_share: float
    maintenance_distribution: tuple[tuple[str, int], ...]
    same_exact_path_matches: int = 0
    same_rule_share: float = 0.0
    same_path_family_share: float = 0.0
    same_exact_path_share: float = 0.0
    dominant_disposition: str | None = None
    dominant_disposition_share: float = 0.0
    disposition_distribution: tuple[tuple[str, int], ...] = ()
    salient_terms: tuple[str, ...] = ()
    resolved_share: float = 0.0
    accepted_share: float = 0.0
    persistent_share: float = 0.0
    quick_fix_share: float = 0.0
    median_resolution_days: float | None = None
    fix_references: tuple[HistoricalFixReference, ...] = ()


@dataclass(frozen=True, slots=True)
class CombinedHistoricalContext:
    local_sonar: IssueContextEvidence | None = None
    local_git: IssueContextEvidence | None = None
    local_prs: IssueContextEvidence | None = None
    local_review_comments: IssueContextEvidence | None = None
    global_dataset: IssueContextEvidence | None = None

    def preferred_evidence(self) -> IssueContextEvidence | None:
        source = self.preferred_source_name()
        if source == "local_sonar":
            return self.local_sonar
        if source == "local_git":
            return self.local_git
        if source == "local_prs":
            return self.local_prs
        if source == "local_review_comments":
            return self.local_review_comments
        if source == "global_dataset":
            return self.global_dataset
        return None

    def preferred_source_name(self) -> str | None:
        for evidence in (
            ("local_sonar", self.local_sonar),
            ("local_git", self.local_git),
            ("local_prs", self.local_prs),
            ("local_review_comments", self.local_review_comments),
            ("global_dataset", self.global_dataset),
        ):
            source_name, source_evidence = evidence
            if source_evidence is not None:
                return source_name
        return None


HistoricalContext = IssueContextEvidence
FIX_REFERENCE_LOOKBACK_DAYS = 365
FIX_REFERENCE_PR_LIMIT = 500
MIN_FIX_REFERENCE_WINDOW_PRS = 3
MAX_FIX_ATTRIBUTION_DELAY_DAYS = 14
RECENCY_DECAY_TAU_DAYS = 180.0
RECENCY_DECAY_FLOOR = 0.35
LOCAL_SONAR_SCORE_SCALE = 20.0
FIX_REFERENCE_RECORD_LIMIT = 100
MIN_FIX_REFERENCE_RECORD_SCORE = 0.6


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
        issue_path = issue.location.path
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        for _, row in similar.iterrows():
            component_path = self._component_path(str(row.get("component", "")))
            if self._path_scope(component_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and self._path_family(component_path) == issue_family:
                same_path_family_matches += 1
            if component_path == issue_path:
                same_exact_path_matches += 1

        sample_size = len(similar)
        same_rule_matches = int((similar["rule"] == issue.rule).sum())
        salient_terms = self._salient_terms(
            issue,
            [f"{str(row.get('message', ''))} {str(row.get('component', ''))}" for _, row in similar.iterrows()],
        )
        resolved_share = self._distribution_share(disposition_distribution, "resolved")
        accepted_share = self._distribution_share(disposition_distribution, "accepted")
        persistent_share = self._distribution_share(disposition_distribution, "persistent")

        return IssueContextEvidence(
            sample_size=sample_size,
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=int((similar["retrieval_score"] >= STRONG_MATCH_SCORE).sum()),
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=self._share(same_rule_matches, sample_size),
            same_path_family_share=self._share(same_path_family_matches, sample_size),
            same_exact_path_share=self._share(same_exact_path_matches, sample_size),
            dominant_disposition=dominant_disposition,
            dominant_disposition_share=dominant_disposition_share,
            disposition_distribution=disposition_distribution,
            salient_terms=salient_terms,
            resolved_share=resolved_share,
            accepted_share=accepted_share,
            persistent_share=persistent_share,
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
    def _distribution(
        values: Iterable[object],
    ) -> tuple[tuple[str, int], ...]:
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
    def _share(count: int, sample_size: int) -> float:
        if sample_size <= 0:
            return 0.0
        return round(count / sample_size, 4)

    @staticmethod
    def _distribution_share(
        distribution: tuple[tuple[str, int], ...],
        label: str,
    ) -> float:
        total = sum(count for _, count in distribution)
        if total <= 0:
            return 0.0
        for current_label, count in distribution:
            if current_label == label:
                return round(count / total, 4)
        return 0.0

    @staticmethod
    def _score_row(issue: SonarIssue, row: pd.Series) -> float:
        score = 0.0

        row_rule = str(row.get("rule", ""))
        row_component = str(row.get("component", ""))
        row_path = GlobalDatasetHistoryRetriever._component_path(row_component)
        issue_path = issue.location.path

        if row_rule == issue.rule:
            score += 7.0
        if row_path == issue_path and issue_path:
            score += 3.5
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

        if GlobalDatasetHistoryRetriever._path_scope(row_path) == GlobalDatasetHistoryRetriever._path_scope(issue_path):
            score += 1.5
        if GlobalDatasetHistoryRetriever._path_family(row_path) == GlobalDatasetHistoryRetriever._path_family(issue_path):
            score += 2.5

        score += 3.0 * GlobalDatasetHistoryRetriever._token_overlap(issue_path, row_path)
        score += 4.0 * GlobalDatasetHistoryRetriever._message_overlap(
            issue.message,
            str(row.get("message", "")),
        )
        score += GlobalDatasetHistoryRetriever._utility_score(row)
        return score

    @staticmethod
    def _utility_score(row: pd.Series) -> float:
        score = 0.5
        if str(row.get("ccs_classification", "")).strip():
            score += 1.0
        if GlobalDatasetHistoryRetriever._disposition_bucket(row) is not None:
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
        tokens = set(GlobalDatasetHistoryRetriever._tokens(path))
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
        left_tokens = set(GlobalDatasetHistoryRetriever._tokens(left))
        right_tokens = set(GlobalDatasetHistoryRetriever._tokens(right))
        if not left_tokens or not right_tokens:
            return 0.0

        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union

    @staticmethod
    def _message_overlap(left: str, right: str) -> float:
        return GlobalDatasetHistoryRetriever._token_overlap(left, right)

    @staticmethod
    def _content_tokens(value: str) -> tuple[str, ...]:
        return tuple(
            token
            for token in GlobalDatasetHistoryRetriever._tokens(value)
            if len(token) > 2 and token not in STOP_TOKENS and not token.isdigit()
        )

    @staticmethod
    def _salient_terms(
        issue: SonarIssue,
        documents: list[str],
        *,
        top_k: int = 3,
    ) -> tuple[str, ...]:
        issue_terms = set(
            GlobalDatasetHistoryRetriever._content_tokens(issue.message)
            + GlobalDatasetHistoryRetriever._content_tokens(issue.location.path)
            + tuple(issue.tags)
        )
        if not issue_terms or not documents:
            return ()

        document_terms = [
            set(GlobalDatasetHistoryRetriever._content_tokens(document))
            for document in documents
        ]
        if not any(document_terms):
            return ()

        scores: list[tuple[str, float]] = []
        document_count = len(document_terms)
        for term in sorted(issue_terms):
            document_frequency = sum(1 for terms in document_terms if term in terms)
            if document_frequency == 0:
                continue
            term_frequency = sum(
                GlobalDatasetHistoryRetriever._content_tokens(document).count(term)
                for document in documents
            )
            idf = math.log((1 + document_count) / (1 + document_frequency)) + 1.0
            scores.append((term, term_frequency * idf))

        scores.sort(key=lambda item: (item[1], item[0]), reverse=True)
        return tuple(term for term, _score in scores[:top_k])


IssueHistoryRetriever = GlobalDatasetHistoryRetriever


class LocalSonarHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        stored_issues = self._store.list_sonar_issues(self._repository_key)
        if not stored_issues:
            self._debug_fix_reference(
                "local_sonar.no_stored_issues",
                issue=issue,
            )
            return None

        scored: list[tuple[SonarIssueRecord, float]] = []
        for record in stored_issues:
            score = self._score_record(issue, record)
            if score >= MIN_RETRIEVAL_SCORE:
                scored.append((record, score))

        if not scored:
            self._debug_fix_reference(
                "local_sonar.no_scored_matches",
                issue=issue,
                total_records=len(stored_issues),
            )
            return None

        scored.sort(
            key=lambda item: (
                item[1],
                item[0].updated_at or "",
                item[0].created_at or "",
            ),
            reverse=True,
        )
        similar = [record for record, _score in scored[:top_k]]
        evidence = self._summarize_matches(issue, similar)
        if not self._has_strong_local_signal(evidence):
            self._debug_fix_reference(
                "local_sonar.weak_signal",
                issue=issue,
                sample_size=evidence.sample_size,
                same_rule_matches=evidence.same_rule_matches,
                same_exact_path_matches=evidence.same_exact_path_matches,
                strong_match_count=evidence.strong_match_count,
            )
            return None
        self._debug_fix_reference(
            "local_sonar.context_ready",
            issue=issue,
            sample_size=evidence.sample_size,
            same_rule_matches=evidence.same_rule_matches,
            same_exact_path_matches=evidence.same_exact_path_matches,
            dominant_disposition=evidence.dominant_disposition,
            resolved_share=evidence.resolved_share,
            fix_reference_count=len(evidence.fix_references),
        )
        return evidence

    def _summarize_matches(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
    ) -> IssueContextEvidence:
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue.location.path)
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue.location.path)
        issue_path = issue.location.path

        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        for record in similar:
            component_path = GlobalDatasetHistoryRetriever._component_path(record.component)
            if GlobalDatasetHistoryRetriever._path_scope(component_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and GlobalDatasetHistoryRetriever._path_family(component_path) == issue_family:
                same_path_family_matches += 1
            if component_path == issue_path:
                same_exact_path_matches += 1

        sample_size = len(similar)
        same_rule_matches = sum(1 for record in similar if record.rule == issue.rule)
        strong_match_count = sum(
            1
            for record in similar
            if self._score_record(issue, record) >= STRONG_MATCH_SCORE
        )
        disposition_distribution = GlobalDatasetHistoryRetriever._distribution(
            disposition
            for disposition in (self._disposition_bucket(record) for record in similar)
            if disposition is not None
        )
        dominant_disposition, dominant_disposition_share = GlobalDatasetHistoryRetriever._dominant_share(
            disposition_distribution,
            sample_size=sum(count for _, count in disposition_distribution),
        )
        salient_terms = GlobalDatasetHistoryRetriever._salient_terms(
            issue,
            [f"{record.message} {record.component}" for record in similar],
        )
        resolution_days = [
            days
            for record in similar
            if (days := self._resolution_days(record)) is not None
        ]
        quick_fix_share = (
            round(sum(1 for days in resolution_days if days <= 7.0) / len(resolution_days), 4)
            if resolution_days
            else 0.0
        )

        return IssueContextEvidence(
            sample_size=sample_size,
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=None,
            dominant_maintenance_share=0.0,
            maintenance_distribution=(),
            same_rule_share=GlobalDatasetHistoryRetriever._share(same_rule_matches, sample_size),
            same_path_family_share=GlobalDatasetHistoryRetriever._share(
                same_path_family_matches,
                sample_size,
            ),
            same_exact_path_share=GlobalDatasetHistoryRetriever._share(
                same_exact_path_matches,
                sample_size,
            ),
            dominant_disposition=dominant_disposition,
            dominant_disposition_share=dominant_disposition_share,
            disposition_distribution=disposition_distribution,
            salient_terms=salient_terms,
            resolved_share=GlobalDatasetHistoryRetriever._distribution_share(
                disposition_distribution,
                "resolved",
            ),
            accepted_share=GlobalDatasetHistoryRetriever._distribution_share(
                disposition_distribution,
                "accepted",
            ),
            persistent_share=GlobalDatasetHistoryRetriever._distribution_share(
                disposition_distribution,
                "persistent",
            ),
            quick_fix_share=quick_fix_share,
            median_resolution_days=self._median_resolution_days(resolution_days),
            fix_references=self._fix_references(issue, similar),
        )

    @staticmethod
    def _has_strong_local_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        if evidence.same_rule_share >= 0.6 and evidence.strong_match_count >= 2:
            return True
        if evidence.same_exact_path_matches >= 2:
            return True
        return (
            evidence.same_path_family_matches >= 3
            and evidence.same_path_family_share >= 0.6
        )

    @staticmethod
    def _score_record(issue: SonarIssue, record: SonarIssueRecord) -> float:
        base_similarity = (
            0.45 * LocalSonarHistoryRetriever._rule_similarity(issue, record)
            + 0.35 * LocalSonarHistoryRetriever._code_similarity(issue, record)
            + 0.20 * LocalSonarHistoryRetriever._location_similarity(issue, record)
        )
        recency_decay = LocalSonarHistoryRetriever._recency_decay(record)
        score = base_similarity * recency_decay * LOCAL_SONAR_SCORE_SCALE
        score += LocalSonarHistoryRetriever._utility_score(record)
        return round(score, 4)

    @staticmethod
    def _rule_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        if record.rule == issue.rule:
            return 1.0
        issue_tags = set(issue.tags)
        record_tags = LocalSonarHistoryRetriever._record_tags(record)
        if issue_tags and issue_tags & record_tags:
            return 0.7
        if (
            record.clean_code_attribute_category
            and record.clean_code_attribute_category == issue.clean_code_attribute_category
        ):
            return 0.7
        if record.clean_code_attribute and record.clean_code_attribute == issue.clean_code_attribute:
            return 0.6
        if record.issue_type == issue.issue_type and issue.issue_type:
            return 0.4
        return 0.0

    @staticmethod
    def _code_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        message_similarity = GlobalDatasetHistoryRetriever._message_overlap(
            issue.message,
            record.message,
        )
        metadata_similarity = 0.0
        if record.issue_type == issue.issue_type and issue.issue_type:
            metadata_similarity += 0.4
        if record.severity == issue.severity and issue.severity:
            metadata_similarity += 0.2
        if set(issue.tags) & LocalSonarHistoryRetriever._record_tags(record):
            metadata_similarity += 0.2
        if (
            record.clean_code_attribute
            and record.clean_code_attribute == issue.clean_code_attribute
        ):
            metadata_similarity += 0.1
        if (
            record.clean_code_attribute_category
            and record.clean_code_attribute_category == issue.clean_code_attribute_category
        ):
            metadata_similarity += 0.1
        metadata_similarity = min(metadata_similarity, 1.0)
        return round((0.7 * message_similarity) + (0.3 * metadata_similarity), 4)

    @staticmethod
    def _location_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        record_path = GlobalDatasetHistoryRetriever._component_path(record.component)
        issue_path = issue.location.path
        if record_path == issue_path and issue_path:
            return 1.0
        if (
            GlobalDatasetHistoryRetriever._path_family(record_path)
            == GlobalDatasetHistoryRetriever._path_family(issue_path)
        ):
            return 0.7
        if (
            GlobalDatasetHistoryRetriever._path_scope(record_path)
            == GlobalDatasetHistoryRetriever._path_scope(issue_path)
        ):
            return 0.4
        return 0.2 * GlobalDatasetHistoryRetriever._token_overlap(issue_path, record_path)

    @staticmethod
    def _recency_decay(record: SonarIssueRecord) -> float:
        observed_at = _parse_timestamp(record.updated_at) or _parse_timestamp(record.created_at)
        if observed_at is None:
            return 1.0
        now = datetime.now(tz=UTC)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age_days = max(0.0, (now - observed_at.astimezone(UTC)).total_seconds() / 86400)
        decay = math.exp(-age_days / RECENCY_DECAY_TAU_DAYS)
        return round(max(RECENCY_DECAY_FLOOR, decay), 4)

    @staticmethod
    def _record_tags(record: SonarIssueRecord) -> set[str]:
        if not record.tags_json:
            return set()
        try:
            raw_tags = json.loads(record.tags_json)
        except json.JSONDecodeError:
            return set()
        if not isinstance(raw_tags, list):
            return set()
        return {str(tag) for tag in raw_tags if isinstance(tag, str)}

    @staticmethod
    def _utility_score(record: SonarIssueRecord) -> float:
        score = 0.5
        if LocalSonarHistoryRetriever._disposition_bucket(record) is not None:
            score += 1.5
        if record.updated_at:
            score += 0.5
        return score

    @staticmethod
    def _disposition_bucket(record: SonarIssueRecord) -> str | None:
        status = (record.status or "").strip().lower()
        resolution = (record.resolution or "").strip().lower()

        if resolution in {"fixed", "resolved", "removed"}:
            return "resolved"
        if resolution in {"wontfix", "won't fix", "false positive", "accepted"}:
            return "accepted"
        if status in {"closed"}:
            return "resolved"
        if status in {"resolved"}:
            return "accepted" if resolution else "resolved"
        if status in {"open", "confirmed", "reopened"}:
            return "persistent"
        return None

    @staticmethod
    def _resolution_days(record: SonarIssueRecord) -> float | None:
        if LocalSonarHistoryRetriever._disposition_bucket(record) != "resolved":
            return None
        created_at = _parse_timestamp(record.created_at)
        updated_at = _parse_timestamp(record.updated_at)
        if created_at is None or updated_at is None or updated_at < created_at:
            return None
        return round((updated_at - created_at).total_seconds() / 86400, 2)

    @staticmethod
    def _median_resolution_days(values: list[float]) -> float | None:
        if not values:
            return None
        sorted_values = sorted(values)
        middle = len(sorted_values) // 2
        if len(sorted_values) % 2 == 1:
            return sorted_values[middle]
        return round((sorted_values[middle - 1] + sorted_values[middle]) / 2, 2)

    def _fix_references(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
        *,
        top_k: int = 3,
    ) -> tuple[HistoricalFixReference, ...]:
        pull_requests = self._bounded_fix_reference_pull_requests([
            pull_request
            for pull_request in self._store.list_pull_requests(self._repository_key)
            if pull_request.merged_at is not None
        ])
        if not pull_requests:
            self._debug_fix_reference(
                "fix_references.no_merged_pull_requests",
                issue=issue,
            )
            return ()

        files_by_pr = {
            pull_request.pr_number: self._store.list_pull_request_files(
                self._repository_key,
                pull_request.pr_number,
            )
            for pull_request in pull_requests
        }
        candidate_records = self._fix_reference_candidate_records(issue, similar)
        self._debug_fix_reference(
            "fix_references.candidate_pool",
            issue=issue,
            pull_request_count=len(pull_requests),
            candidate_count=len(candidate_records),
            candidate_issue_keys=",".join(record.issue_key for record in candidate_records[:10]),
        )
        references: list[HistoricalFixReference] = []
        seen_prs: set[int] = set()
        for record in candidate_records:
            if self._disposition_bucket(record) != "resolved":
                self._debug_fix_reference(
                    "fix_references.skip_unresolved_record",
                    issue=issue,
                    record_issue_key=record.issue_key,
                    record_rule=record.rule,
                    record_component=record.component,
                    record_status=record.status,
                    record_resolution=record.resolution,
                )
                continue
            reference = self._fix_reference_for_record(
                issue,
                record,
                pull_requests,
                files_by_pr,
            )
            if reference is None or reference.pr_number in seen_prs:
                continue
            references.append(reference)
            seen_prs.add(reference.pr_number)
            if len(references) >= top_k:
                break

        result = tuple(references)
        self._debug_fix_reference(
            "fix_references.result",
            issue=issue,
            reference_count=len(result),
            reference_prs=",".join(str(reference.pr_number) for reference in result),
        )
        return result

    def _fix_reference_candidate_records(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
    ) -> list[SonarIssueRecord]:
        candidates: dict[str, tuple[SonarIssueRecord, float]] = {}

        for record in similar:
            candidates[record.issue_key] = (record, 1.0)

        for record in self._store.list_sonar_issues(self._repository_key):
            score = self._fix_reference_record_score(issue, record)
            if score < MIN_FIX_REFERENCE_RECORD_SCORE:
                continue
            existing = candidates.get(record.issue_key)
            if existing is None or score > existing[1]:
                candidates[record.issue_key] = (record, score)

        ranked = sorted(
            candidates.values(),
            key=lambda item: (
                item[1],
                item[0].updated_at or "",
                item[0].created_at or "",
                item[0].issue_key,
            ),
            reverse=True,
        )
        self._debug_fix_reference(
            "fix_references.candidate_ranking",
            issue=issue,
            top_candidates=",".join(
                f"{record.issue_key}:{score}"
                for record, score in ranked[:10]
            ),
        )
        return [record for record, _score in ranked[:FIX_REFERENCE_RECORD_LIMIT]]

    @staticmethod
    def _fix_reference_record_score(issue: SonarIssue, record: SonarIssueRecord) -> float:
        if LocalSonarHistoryRetriever._disposition_bucket(record) != "resolved":
            return 0.0
        rule_score = LocalSonarHistoryRetriever._rule_similarity(issue, record)
        location_score = LocalSonarHistoryRetriever._location_similarity(issue, record)
        if rule_score <= 0.0 and location_score <= 0.0:
            return 0.0
        score = (0.6 * rule_score) + (0.4 * location_score)
        return round(score, 4)

    def _fix_reference_for_record(
        self,
        issue: SonarIssue,
        record: SonarIssueRecord,
        pull_requests: list[PullRequestRecord],
        files_by_pr: dict[int, list[PullRequestFileRecord]],
    ) -> HistoricalFixReference | None:
        resolved_at = _parse_timestamp(record.updated_at)
        if resolved_at is None:
            self._debug_fix_reference(
                "fix_reference_record.missing_resolved_at",
                issue=issue,
                record_issue_key=record.issue_key,
            )
            return None

        record_path = GlobalDatasetHistoryRetriever._component_path(record.component)
        candidates: list[tuple[PullRequestRecord, int]] = []
        for pull_request in pull_requests:
            merged_at = _parse_timestamp(pull_request.merged_at)
            if merged_at is None or merged_at > resolved_at:
                self._debug_fix_reference(
                    "fix_reference_record.skip_pr_after_resolution",
                    issue=issue,
                    record_issue_key=record.issue_key,
                    record_path=record_path,
                    pr_number=pull_request.pr_number,
                    pr_merged_at=pull_request.merged_at,
                    resolved_at=record.updated_at,
                )
                continue
            age = resolved_at - merged_at
            if age < timedelta(0) or age > timedelta(days=MAX_FIX_ATTRIBUTION_DELAY_DAYS):
                self._debug_fix_reference(
                    "fix_reference_record.skip_pr_outside_window",
                    issue=issue,
                    record_issue_key=record.issue_key,
                    record_path=record_path,
                    pr_number=pull_request.pr_number,
                    pr_merged_at=pull_request.merged_at,
                    resolved_at=record.updated_at,
                    age_days=round(age.total_seconds() / 86400, 4),
                )
                continue
            if not self._pull_request_touches_path(
                files_by_pr.get(pull_request.pr_number, []),
                record_path,
            ):
                self._debug_fix_reference(
                    "fix_reference_record.skip_pr_missing_file_touch",
                    issue=issue,
                    record_issue_key=record.issue_key,
                    record_path=record_path,
                    pr_number=pull_request.pr_number,
                )
                continue
            candidates.append((pull_request, int(age.total_seconds())))

        if not candidates:
            self._debug_fix_reference(
                "fix_reference_record.no_viable_pr_candidates",
                issue=issue,
                record_issue_key=record.issue_key,
                record_rule=record.rule,
                record_component=record.component,
                resolved_at=record.updated_at,
            )
            return None

        candidates.sort(key=lambda item: (item[1], -item[0].pr_number))
        pull_request = candidates[0][0]
        files = files_by_pr.get(pull_request.pr_number, [])
        confidence = self._fix_reference_confidence(issue, record, files)
        if confidence < 0.7:
            self._debug_fix_reference(
                "fix_reference_record.reject_low_confidence",
                issue=issue,
                record_issue_key=record.issue_key,
                pr_number=pull_request.pr_number,
                confidence=confidence,
            )
            return None

        reference = HistoricalFixReference(
            pr_number=pull_request.pr_number,
            pr_title=pull_request.title,
            pr_url=self._pull_request_url(pull_request.pr_number),
            file_url=f"{self._pull_request_url(pull_request.pr_number)}/files",
            file_path=record_path,
            resolved_at=record.updated_at or "",
            confidence=confidence,
            evidence=self._fix_reference_evidence(issue, record, files),
        )
        self._debug_fix_reference(
            "fix_reference_record.accepted",
            issue=issue,
            record_issue_key=record.issue_key,
            pr_number=reference.pr_number,
            confidence=reference.confidence,
            evidence=" | ".join(reference.evidence),
        )
        return reference

    @staticmethod
    def _pull_request_touches_path(
        files: list[PullRequestFileRecord],
        issue_path: str,
    ) -> bool:
        return any(file_record.file_path == issue_path for file_record in files)

    @staticmethod
    def _bounded_fix_reference_pull_requests(
        pull_requests: list[PullRequestRecord],
    ) -> list[PullRequestRecord]:
        dated_pull_requests = [
            (pull_request, merged_at)
            for pull_request in pull_requests
            if (merged_at := _parse_timestamp(pull_request.merged_at)) is not None
        ]
        if not dated_pull_requests:
            return []

        dated_pull_requests.sort(
            key=lambda item: (item[1], item[0].pr_number),
            reverse=True,
        )
        newest_merge = dated_pull_requests[0][1]
        cutoff = newest_merge - timedelta(days=FIX_REFERENCE_LOOKBACK_DAYS)
        time_window = [
            pull_request
            for pull_request, merged_at in dated_pull_requests
            if merged_at >= cutoff
        ]
        count_window = [
            pull_request
            for pull_request, _merged_at in dated_pull_requests[:FIX_REFERENCE_PR_LIMIT]
        ]

        if len(time_window) >= MIN_FIX_REFERENCE_WINDOW_PRS:
            return time_window[:FIX_REFERENCE_PR_LIMIT]
        return count_window

    @staticmethod
    def _fix_reference_confidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        files: list[PullRequestFileRecord],
    ) -> float:
        record_path = GlobalDatasetHistoryRetriever._component_path(record.component)
        confidence = 0.0
        if record.rule == issue.rule:
            confidence += 0.3
        if record_path == issue.location.path:
            confidence += 0.25
        if any(file_record.file_path == record_path for file_record in files):
            confidence += 0.25
        if record.line is not None:
            confidence += 0.1
        if not any(
            LocalSonarHistoryRetriever._is_analysis_config_path(file_record.file_path)
            for file_record in files
        ):
            confidence += 0.1
        return round(min(confidence, 1.0), 2)

    @staticmethod
    def _fix_reference_evidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        files: list[PullRequestFileRecord],
    ) -> tuple[str, ...]:
        evidence = [
            f"same Sonar rule `{record.rule}`",
            "Sonar marked the historical issue as fixed/resolved",
        ]
        record_path = GlobalDatasetHistoryRetriever._component_path(record.component)
        if record_path == issue.location.path:
            evidence.append(f"same file `{record_path}`")
        elif any(file_record.file_path == record_path for file_record in files):
            evidence.append(f"PR touched historical file `{record_path}`")
        if record.line is not None:
            evidence.append(f"historical issue was near line {record.line}")
        if any(
            LocalSonarHistoryRetriever._is_analysis_config_path(file_record.file_path)
            for file_record in files
        ):
            evidence.append("PR also touched analysis configuration, so confidence is lower")
        return tuple(evidence)

    @staticmethod
    def _is_analysis_config_path(path: str) -> bool:
        normalized = path.lower()
        filename = Path(normalized).name
        return (
            filename in {"sonar-project.properties", "pom.xml", "build.gradle", "build.gradle.kts"}
            or normalized.startswith(".github/workflows/")
            or "quality-profile" in normalized
            or "ruleset" in normalized
        )

    def _pull_request_url(self, pr_number: int) -> str:
        return f"https://github.com/{self._repository_key}/pull/{pr_number}"

    def _debug_fix_reference(
        self,
        event: str,
        *,
        issue: SonarIssue,
        **extra: object,
    ) -> None:
        fix_reference_debug_logger.debug(
            event,
            extra={
                "repository": self._repository_key,
                "issue_key": issue.key,
                "issue_rule": issue.rule,
                "issue_path": issue.location.path,
                "issue_line": issue.location.line,
                **extra,
            },
        )


class LocalGitHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        commits = self._store.list_git_commits(self._repository_key)
        if not commits:
            return None

        touches = self._store.list_git_file_touches(self._repository_key)
        touches_by_commit: dict[str, list[GitFileTouchRecord]] = {}
        for touch in touches:
            touches_by_commit.setdefault(touch.commit_sha, []).append(touch)

        scored: list[tuple[GitCommitRecord, list[GitFileTouchRecord], float]] = []
        for commit in commits:
            commit_touches = touches_by_commit.get(commit.commit_sha, [])
            if not commit_touches:
                continue
            score = self._score_commit(issue, commit_touches)
            if score >= 1.0:
                scored.append((commit, commit_touches, score))

        if not scored:
            return None

        scored.sort(
            key=lambda item: (item[2], item[0].authored_at, item[0].commit_sha),
            reverse=True,
        )
        relevant = scored[:top_k]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_git_signal(evidence):
            return None
        return evidence

    def _summarize_matches(
        self,
        issue: SonarIssue,
        relevant: list[tuple[GitCommitRecord, list[GitFileTouchRecord], float]],
    ) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue_path)

        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        for _commit, touches, score in relevant:
            exact = any(touch.file_path == issue_path for touch in touches)
            family = any(
                issue_family and touch.module_family == issue_family
                for touch in touches
            )
            scope = any(
                GlobalDatasetHistoryRetriever._path_scope(touch.file_path) == issue_scope
                for touch in touches
            )
            if scope:
                same_scope_matches += 1
            if family:
                same_path_family_matches += 1
            if exact:
                same_exact_path_matches += 1
            if score >= 3.0:
                strong_match_count += 1

        maintenance_buckets = [
            self._maintenance_bucket_from_commit(commit.classification)
            for commit, _touches, _score in relevant
        ]
        maintenance_distribution = GlobalDatasetHistoryRetriever._distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = GlobalDatasetHistoryRetriever._dominant_share(
            maintenance_distribution,
            sample_size=len(relevant),
        )

        sonar_issues = self._store.list_sonar_issues(self._repository_key)
        same_rule_history = [
            record
            for record in sonar_issues
            if record.rule == issue.rule and self._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(len(same_rule_history), len(relevant))
        salient_terms = GlobalDatasetHistoryRetriever._salient_terms(
            issue,
            [
                f"{commit.message} "
                + " ".join(touch.file_path for touch in touches)
                for commit, touches, _score in relevant
            ],
        )

        return IssueContextEvidence(
            sample_size=len(relevant),
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=GlobalDatasetHistoryRetriever._share(same_rule_matches, len(relevant)),
            same_path_family_share=GlobalDatasetHistoryRetriever._share(
                same_path_family_matches,
                len(relevant),
            ),
            same_exact_path_share=GlobalDatasetHistoryRetriever._share(
                same_exact_path_matches,
                len(relevant),
            ),
            salient_terms=salient_terms,
        )

    @staticmethod
    def _score_commit(issue: SonarIssue, touches: list[GitFileTouchRecord]) -> float:
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue_path)
        score = 0.0
        if any(touch.file_path == issue_path for touch in touches):
            score += 3.5
        if issue_family and any(touch.module_family == issue_family for touch in touches):
            score += 2.5
        if any(
            GlobalDatasetHistoryRetriever._path_scope(touch.file_path) == issue_scope
            for touch in touches
        ):
            score += 1.0
        unique_paths = {touch.file_path for touch in touches}
        score += max(0.0, min(1.5, len(unique_paths) * 0.25))
        return score

    @staticmethod
    def _has_strong_git_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        if evidence.same_exact_path_matches >= 2:
            return True
        return (
            evidence.same_path_family_matches >= 3
            and evidence.same_path_family_share >= 0.6
        )

    @staticmethod
    def _maintenance_bucket_from_commit(classification: str) -> str:
        normalized = classification.strip().lower()
        if normalized == "fix":
            return "behavior"
        if normalized in {"test", "docs", "build"}:
            return "supporting"
        return "cleanup"

    @staticmethod
    def _rule_history_is_relevant(issue: SonarIssue, component: str) -> bool:
        record_path = GlobalDatasetHistoryRetriever._component_path(component)
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        return (
            record_path == issue_path
            or (
                bool(issue_family)
                and GlobalDatasetHistoryRetriever._path_family(record_path) == issue_family
            )
        )


class LocalPullRequestHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        pull_requests = self._store.list_pull_requests(self._repository_key)
        if not pull_requests:
            return None

        files_by_pr = {
            pull_request.pr_number: self._store.list_pull_request_files(
                self._repository_key,
                pull_request.pr_number,
            )
            for pull_request in pull_requests
        }
        scored: list[tuple[PullRequestRecord, list[PullRequestFileRecord], float]] = []
        for pull_request in pull_requests:
            files = files_by_pr.get(pull_request.pr_number, [])
            if not files:
                continue
            score = self._score_pull_request(issue, files)
            if score >= 1.0:
                scored.append((pull_request, files, score))

        if not scored:
            return None

        scored.sort(
            key=lambda item: (item[2], item[0].updated_at or "", item[0].pr_number),
            reverse=True,
        )
        relevant = scored[:top_k]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_signal(evidence):
            return None
        return evidence

    def _summarize_matches(
        self,
        issue: SonarIssue,
        relevant: list[tuple[PullRequestRecord, list[PullRequestFileRecord], float]],
    ) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue_path)

        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        maintenance_buckets: list[str] = []
        for pull_request, files, score in relevant:
            exact = any(file_record.file_path == issue_path for file_record in files)
            family = any(
                issue_family
                and GlobalDatasetHistoryRetriever._path_family(file_record.file_path) == issue_family
                for file_record in files
            )
            scope = any(
                GlobalDatasetHistoryRetriever._path_scope(file_record.file_path) == issue_scope
                for file_record in files
            )
            if scope:
                same_scope_matches += 1
            if family:
                same_path_family_matches += 1
            if exact:
                same_exact_path_matches += 1
            if score >= 3.0:
                strong_match_count += 1
            maintenance_buckets.append(
                self._maintenance_bucket_from_text(f"{pull_request.title}\n{pull_request.body or ''}")
            )

        maintenance_distribution = GlobalDatasetHistoryRetriever._distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = GlobalDatasetHistoryRetriever._dominant_share(
            maintenance_distribution,
            sample_size=len(relevant),
        )
        same_rule_history = [
            record
            for record in self._store.list_sonar_issues(self._repository_key)
            if record.rule == issue.rule and LocalGitHistoryRetriever._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(
            max(len(same_rule_history), same_exact_path_matches),
            len(relevant),
        )
        salient_terms = GlobalDatasetHistoryRetriever._salient_terms(
            issue,
            [
                f"{pull_request.title} {pull_request.body or ''} "
                + " ".join(file_record.file_path for file_record in files)
                for pull_request, files, _score in relevant
            ],
        )

        return IssueContextEvidence(
            sample_size=len(relevant),
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=GlobalDatasetHistoryRetriever._share(same_rule_matches, len(relevant)),
            same_path_family_share=GlobalDatasetHistoryRetriever._share(
                same_path_family_matches,
                len(relevant),
            ),
            same_exact_path_share=GlobalDatasetHistoryRetriever._share(
                same_exact_path_matches,
                len(relevant),
            ),
            salient_terms=salient_terms,
        )

    @staticmethod
    def _score_pull_request(issue: SonarIssue, files: list[PullRequestFileRecord]) -> float:
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue_path)
        score = 0.0
        if any(file_record.file_path == issue_path for file_record in files):
            score += 3.5
        if issue_family and any(
            GlobalDatasetHistoryRetriever._path_family(file_record.file_path) == issue_family
            for file_record in files
        ):
            score += 2.0
        if any(
            GlobalDatasetHistoryRetriever._path_scope(file_record.file_path) == issue_scope
            for file_record in files
        ):
            score += 1.0
        return score

    @staticmethod
    def _has_strong_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        if evidence.same_exact_path_matches >= 2:
            return True
        return (
            evidence.same_path_family_matches >= 3
            and evidence.same_path_family_share >= 0.6
        )

    @staticmethod
    def _maintenance_bucket_from_text(text: str) -> str:
        normalized = text.lower()
        if any(token in normalized for token in ("fix", "bug", "hotfix", "behavior")):
            return "behavior"
        if any(token in normalized for token in ("test", "docs", "readme", "workflow", "ci", "build")):
            return "supporting"
        return "cleanup"


class LocalReviewCommentHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        comments = self._store.list_all_pull_request_review_comments(self._repository_key)
        if not comments:
            return None

        scored: list[tuple[PullRequestReviewCommentRecord, float]] = []
        for comment in comments:
            score = self._score_comment(issue, comment)
            if score >= 1.0:
                scored.append((comment, score))

        if not scored:
            return None

        scored.sort(
            key=lambda item: (item[1], item[0].updated_at or "", item[0].comment_id),
            reverse=True,
        )
        relevant = [comment for comment, _score in scored[:top_k]]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_signal(evidence):
            return None
        return evidence

    def _summarize_matches(
        self,
        issue: SonarIssue,
        relevant: list[PullRequestReviewCommentRecord],
    ) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        issue_scope = GlobalDatasetHistoryRetriever._path_scope(issue_path)

        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        maintenance_buckets: list[str] = []
        for comment in relevant:
            file_path = comment.file_path or ""
            if GlobalDatasetHistoryRetriever._path_scope(file_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and GlobalDatasetHistoryRetriever._path_family(file_path) == issue_family:
                same_path_family_matches += 1
            if file_path == issue_path:
                same_exact_path_matches += 1
            if file_path == issue_path:
                strong_match_count += 1
            maintenance_buckets.append(self._maintenance_bucket_from_text(comment.body))

        maintenance_distribution = GlobalDatasetHistoryRetriever._distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = GlobalDatasetHistoryRetriever._dominant_share(
            maintenance_distribution,
            sample_size=len(relevant),
        )
        same_rule_history = [
            record
            for record in self._store.list_sonar_issues(self._repository_key)
            if record.rule == issue.rule and LocalGitHistoryRetriever._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(
            max(len(same_rule_history), same_exact_path_matches),
            len(relevant),
        )
        salient_terms = GlobalDatasetHistoryRetriever._salient_terms(
            issue,
            [
                f"{comment.body} {comment.file_path or ''}"
                for comment in relevant
            ],
        )

        return IssueContextEvidence(
            sample_size=len(relevant),
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=GlobalDatasetHistoryRetriever._share(same_rule_matches, len(relevant)),
            same_path_family_share=GlobalDatasetHistoryRetriever._share(
                same_path_family_matches,
                len(relevant),
            ),
            same_exact_path_share=GlobalDatasetHistoryRetriever._share(
                same_exact_path_matches,
                len(relevant),
            ),
            salient_terms=salient_terms,
        )

    @staticmethod
    def _score_comment(issue: SonarIssue, comment: PullRequestReviewCommentRecord) -> float:
        file_path = comment.file_path or ""
        issue_path = issue.location.path
        issue_family = GlobalDatasetHistoryRetriever._path_family(issue_path)
        score = 0.0
        if file_path == issue_path:
            score += 3.0
        if issue_family and GlobalDatasetHistoryRetriever._path_family(file_path) == issue_family:
            score += 1.5
        score += 2.0 * GlobalDatasetHistoryRetriever._message_overlap(issue.message, comment.body)
        if issue.rule.lower() in comment.body.lower():
            score += 1.5
        return score

    @staticmethod
    def _has_strong_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        return evidence.same_exact_path_matches >= 2

    @staticmethod
    def _maintenance_bucket_from_text(text: str) -> str:
        normalized = text.lower()
        if any(token in normalized for token in ("behavior", "semantic", "correctness", "break")):
            return "behavior"
        if any(token in normalized for token in ("test", "docs", "comment", "naming")):
            return "supporting"
        return "cleanup"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip()
    for candidate in (
        normalized,
        normalized.replace("Z", "+00:00"),
    ):
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
