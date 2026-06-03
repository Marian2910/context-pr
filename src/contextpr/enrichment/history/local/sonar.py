from __future__ import annotations

import contextpr.enrichment.history.local.sonar_fix_refs as sonar_fix_refs
import contextpr.enrichment.history.local.sonar_scoring as sonar_scoring
from contextpr.enrichment.history.constants import MIN_RETRIEVAL_SCORE, STRONG_MATCH_SCORE
from contextpr.enrichment.history.types import (
    HistoricalFixReference,
    IssueContextEvidence,
)
from contextpr.enrichment.history.utils import (
    component_path,
    distribution,
    distribution_share,
    dominant_share,
    path_family,
    path_scope,
    salient_terms,
    share,
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
    ) -> IssueContextEvidence | None:
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
        similar = [record for record, _score in scored[:top_k]]
        evidence = self._summarize_matches(issue, similar)
        if not self._has_strong_local_signal(evidence):
            return None
        return evidence

    def _list_sonar_issues(self) -> list[SonarIssueRecord]:
        if self._stored_issues is None:
            self._stored_issues = self._store.list_sonar_issues(self._repository_key)
        return self._stored_issues

    def _summarize_matches(
        self,
        issue: SonarIssue,
        similar: list[SonarIssueRecord],
    ) -> IssueContextEvidence:
        issue_scope = path_scope(issue.location.path)
        issue_family = path_family(issue.location.path)
        issue_path = issue.location.path
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        for record in similar:
            record_path = component_path(record.component)
            if path_scope(record_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and path_family(record_path) == issue_family:
                same_path_family_matches += 1
            if record_path == issue_path:
                same_exact_path_matches += 1
        sample_size = len(similar)
        same_rule_matches = sum(1 for record in similar if record.rule == issue.rule)
        strong_match_count = sum(
            1
            for record in similar
            if self._score_record(issue, record) >= STRONG_MATCH_SCORE
        )
        disposition_distribution = distribution(
            disposition
            for disposition in (self._disposition_bucket(record) for record in similar)
            if disposition is not None
        )
        dominant_disposition, dominant_disposition_share = dominant_share(
            disposition_distribution,
            sample_size=sum(count for _, count in disposition_distribution),
        )
        issue_salient_terms = salient_terms(
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
        return evidence.same_path_family_matches >= 3 and evidence.same_path_family_share >= 0.6

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
