from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class CombinedHistoricalContext:
    local_sonar: IssueContextEvidence | None = None
    local_git: IssueContextEvidence | None = None
    local_prs: IssueContextEvidence | None = None
    local_review_comments: IssueContextEvidence | None = None
    global_dataset: IssueContextEvidence | None = None

    def preferred_evidence(self) -> IssueContextEvidence | None:
        source = self.preferred_source_name()
        if source is None:
            return None
        return getattr(self, source)

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
            return None

        scored: list[tuple[SonarIssueRecord, float]] = []
        for record in stored_issues:
            score = self._score_record(issue, record)
            if score >= MIN_RETRIEVAL_SCORE:
                scored.append((record, score))

        if not scored:
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
            return None
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
        score = 0.0
        record_path = GlobalDatasetHistoryRetriever._component_path(record.component)
        issue_path = issue.location.path

        if record.rule == issue.rule:
            score += 7.0
        if record_path == issue_path and issue_path:
            score += 3.5
        if record.issue_type == issue.issue_type and issue.issue_type:
            score += 2.5
        if record.severity == issue.severity and issue.severity:
            score += 1.5

        record_tags = set()
        if record.tags_json:
            try:
                raw_tags = json.loads(record.tags_json)
            except json.JSONDecodeError:
                raw_tags = []
            if isinstance(raw_tags, list):
                record_tags = {str(tag) for tag in raw_tags if isinstance(tag, str)}
        score += float(len(set(issue.tags) & record_tags))

        if (
            GlobalDatasetHistoryRetriever._path_scope(record_path)
            == GlobalDatasetHistoryRetriever._path_scope(issue_path)
        ):
            score += 1.5
        if (
            GlobalDatasetHistoryRetriever._path_family(record_path)
            == GlobalDatasetHistoryRetriever._path_family(issue_path)
        ):
            score += 2.5

        score += 3.0 * GlobalDatasetHistoryRetriever._token_overlap(issue_path, record_path)
        score += 4.0 * GlobalDatasetHistoryRetriever._message_overlap(issue.message, record.message)
        score += LocalSonarHistoryRetriever._utility_score(record)
        return score

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
                issue_family
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
