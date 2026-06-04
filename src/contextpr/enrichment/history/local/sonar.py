from __future__ import annotations

import contextpr.enrichment.history.local.sonar_fix_refs as sonar_fix_refs
import contextpr.enrichment.history.local.sonar_scoring as sonar_scoring
from contextpr.enrichment.history.constants import MIN_RETRIEVAL_SCORE
from contextpr.enrichment.history.types import (
    LOCAL_SONAR_SCORE_SCALE,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalFixReference,
    HistoricalIssueCase,
)
from contextpr.enrichment.history.utils import (
    component_path,
    path_family,
)
from contextpr.models import SonarIssue
from contextpr.persistence import (
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    SonarIssueRecord,
)


class LocalSonarHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key
        self._stored_issues: list[SonarIssueRecord] | None = None

    def find_context(
        self,
        issue: SonarIssue,
        *,
        top_k: int = 25,
    ) -> HistoricalEvidenceSummary | None:
        stored_issues = self._list_sonar_issues()
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
        evidence = self._summarize_matches(issue, scored[:top_k])
        if not evidence.cases:
            return None
        return evidence

    def _list_sonar_issues(self) -> list[SonarIssueRecord]:
        if self._stored_issues is None:
            self._stored_issues = self._store.list_sonar_issues(self._repository_key)
        return self._stored_issues

    def _summarize_matches(
        self,
        issue: SonarIssue,
        similar: list[tuple[SonarIssueRecord, float]],
    ) -> HistoricalEvidenceSummary:
        issue_family = path_family(issue.location.path)
        issue_path = issue.location.path
        records = [record for record, _score in similar]
        fix_references = self._fix_references(issue, records)
        cases = tuple(
            sorted(
                (
                    self._historical_case(issue, record, score, fix_references)
                    for record, score in similar
                ),
                key=lambda case: (
                    case.confidence,
                    case.fix_reference is not None,
                    case.similarity_score,
                ),
                reverse=True,
            )
        )
        return HistoricalEvidenceSummary(
            source_name="local_sonar",
            cases=cases,
            related_cases_count=len(records),
            close_cases_count=sum(
                1
                for case in cases
                if case.rule == issue.rule
                and (
                    case.file_path == issue_path
                    or (issue_family and path_family(case.file_path) == issue_family)
                )
            ),
            fixed_cases_count=sum(1 for case in cases if case.disposition == "resolved"),
            accepted_cases_count=sum(1 for case in cases if case.disposition == "accepted"),
            persistent_cases_count=sum(1 for case in cases if case.disposition == "persistent"),
        )

    @staticmethod
    def _has_strong_local_signal(evidence: HistoricalEvidenceSummary) -> bool:
        return evidence.best_case() is not None

    def _historical_case(
        self,
        issue: SonarIssue,
        record: SonarIssueRecord,
        score: float,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalIssueCase:
        record_path = component_path(record.component)
        disposition = self._disposition_bucket(record)
        fix_reference = self._fix_reference_for_case(record, fix_references)
        case_type = self._case_type(issue, disposition, fix_reference)
        confidence = self._case_confidence(issue, record, score, disposition, fix_reference)
        return HistoricalIssueCase(
            issue_key=record.issue_key,
            rule=record.rule,
            message=record.message,
            file_path=record_path,
            line=record.line,
            disposition=disposition,
            similarity_score=round(min(score / LOCAL_SONAR_SCORE_SCALE, 1.0), 4),
            confidence=confidence,
            case_type=case_type,
            evidence=self._case_evidence(issue, record, disposition, fix_reference),
            fix_reference=fix_reference,
        )

    @staticmethod
    def _fix_reference_for_case(
        record: SonarIssueRecord,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalFixReference | None:
        record_path = component_path(record.component)
        for reference in fix_references:
            if reference.file_path == record_path:
                return reference
        return None

    @staticmethod
    def _case_type(
        issue: SonarIssue,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> HistoricalCaseType:
        if issue.issue_type == "BUG":
            return HistoricalCaseType.REVIEW_CAREFULLY
        if disposition == "accepted":
            return HistoricalCaseType.DEFERRED
        if disposition == "persistent":
            return HistoricalCaseType.PERSISTENT
        if disposition == "resolved" or fix_reference is not None:
            return HistoricalCaseType.PREVIOUS_FIX
        return HistoricalCaseType.PERSISTENT

    @staticmethod
    def _case_confidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        score: float,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> float:
        if fix_reference is not None:
            return fix_reference.confidence
        record_path = component_path(record.component)
        confidence = 0.45 * min(score / LOCAL_SONAR_SCORE_SCALE, 1.0)
        if record.rule == issue.rule:
            confidence += 0.2
        if record_path == issue.location.path:
            confidence += 0.2
        elif path_family(record_path) == path_family(issue.location.path):
            confidence += 0.12
        if disposition in {"resolved", "accepted", "persistent"}:
            confidence += 0.1
        if record.line is not None:
            confidence += 0.05
        return round(min(confidence, 1.0), 2)

    @staticmethod
    def _case_evidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> tuple[str, ...]:
        evidence: list[str] = []
        if record.rule == issue.rule:
            evidence.append(f"same rule `{record.rule}`")
        record_path = component_path(record.component)
        if record_path == issue.location.path:
            evidence.append("same file")
        elif path_family(record_path) == path_family(issue.location.path):
            evidence.append("same module")
        if disposition == "resolved":
            evidence.append("historical case was fixed")
        elif disposition == "accepted":
            evidence.append("historical case was accepted/deferred")
        elif disposition == "persistent":
            evidence.append("historical case remained open")
        if fix_reference is not None:
            evidence.append(f"linked to PR #{fix_reference.pr_number}")
        return tuple(evidence)

    @staticmethod
    def _score_record(issue: SonarIssue, record: SonarIssueRecord) -> float:
        return sonar_scoring.score_record(issue, record)

    @staticmethod
    def _rule_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        return sonar_scoring.rule_similarity(issue, record)

    @staticmethod
    def _code_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        return sonar_scoring.code_similarity(issue, record)

    @staticmethod
    def _location_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        return sonar_scoring.location_similarity(issue, record)

    @staticmethod
    def _recency_decay(record: SonarIssueRecord) -> float:
        return sonar_scoring.recency_decay(record)

    @staticmethod
    def _record_tags(record: SonarIssueRecord) -> set[str]:
        return sonar_scoring.record_tags(record)

    @staticmethod
    def _utility_score(record: SonarIssueRecord) -> float:
        return sonar_scoring.utility_score(record)

    @staticmethod
    def _disposition_bucket(record: SonarIssueRecord) -> str | None:
        return sonar_scoring.disposition_bucket(record)

    @staticmethod
    def _resolution_days(record: SonarIssueRecord) -> float | None:
        return sonar_scoring.resolution_days(record)

    @staticmethod
    def _median_resolution_days(values: list[float]) -> float | None:
        return sonar_scoring.median_resolution_days(values)

    def _fix_references(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
        *,
        top_k: int = 3,
    ) -> tuple[HistoricalFixReference, ...]:
        return sonar_fix_refs.fix_references(
            store=self._store,
            repository_key=self._repository_key,
            issue=issue,
            similar=similar,
            top_k=top_k,
        )

    def _fix_reference_candidate_records(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
    ) -> list[SonarIssueRecord]:
        return sonar_fix_refs.fix_reference_candidate_records(
            store=self._store,
            repository_key=self._repository_key,
            issue=issue,
            similar=similar,
        )

    @staticmethod
    def _fix_reference_record_score(issue: SonarIssue, record: SonarIssueRecord) -> float:
        return sonar_fix_refs.fix_reference_record_score(issue, record)

    def _fix_reference_for_record(
        self,
        issue: SonarIssue,
        record: SonarIssueRecord,
        pull_requests: list[PullRequestRecord],
        files_by_pr: dict[int, list[PullRequestFileRecord]],
    ) -> HistoricalFixReference | None:
        return sonar_fix_refs.fix_reference_for_record(
            repository_key=self._repository_key,
            issue=issue,
            record=record,
            pull_requests=pull_requests,
            files_by_pr=files_by_pr,
        )

    @staticmethod
    def _pull_request_touches_path(files: list[PullRequestFileRecord], issue_path: str) -> bool:
        return sonar_fix_refs.pull_request_touches_path(files, issue_path)

    @staticmethod
    def _bounded_fix_reference_pull_requests(
        pull_requests: list[PullRequestRecord],
    ) -> list[PullRequestRecord]:
        return sonar_fix_refs.bounded_fix_reference_pull_requests(pull_requests)

    @staticmethod
    def _fix_reference_confidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        files: list[PullRequestFileRecord],
    ) -> float:
        return sonar_fix_refs.fix_reference_confidence(issue, record, files)

    @staticmethod
    def _location_confidence_bonus(issue_path: str, record_path: str) -> float:
        return sonar_fix_refs.location_confidence_bonus(issue_path, record_path)

    @staticmethod
    def _fix_reference_evidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        files: list[PullRequestFileRecord],
    ) -> tuple[str, ...]:
        return sonar_fix_refs.fix_reference_evidence(issue, record, files)

    @staticmethod
    def _is_analysis_config_path(path: str) -> bool:
        return sonar_fix_refs.is_analysis_config_path(path)

    def _pull_request_url(self, pr_number: int) -> str:
        return sonar_fix_refs.pull_request_url(self._repository_key, pr_number)
