from __future__ import annotations

import contextpr.enrichment.history.local.sonar_scoring as sonar_scoring
from contextpr.enrichment.history.constants import MIN_RETRIEVAL_SCORE
from contextpr.enrichment.history.local.cases import (
    LocalHistoryCaseBuilder,
    LocalHistoryCaseInput,
)
from contextpr.enrichment.history.local.fix_references import (
    FixReferenceResolutionContext,
    FixReferenceResolver,
)
from contextpr.enrichment.history.types import HistoricalEvidenceSummary, HistoricalFixReference
from contextpr.enrichment.history.utils import path_family
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore, SonarIssueRecord


class LocalSonarHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key
        self._stored_issues: list[SonarIssueRecord] | None = None
        self._fix_reference_resolver = FixReferenceResolver()
        self._case_builder = LocalHistoryCaseBuilder()

    def find_context(
        self,
        issue: SonarIssue,
        *,
        top_k: int = 25,
    ) -> HistoricalEvidenceSummary | None:
        similar = self._similar_records(issue, top_k=top_k)
        if not similar:
            return None
        evidence = self._summarize_matches(issue, similar)
        if not evidence.cases:
            return None
        return evidence

    def _similar_records(
        self,
        issue: SonarIssue,
        *,
        top_k: int,
    ) -> list[tuple[SonarIssueRecord, float]]:
        scored = [
            (record, score)
            for record in self._list_sonar_issues()
            if (score := sonar_scoring.score_record(issue, record)) >= MIN_RETRIEVAL_SCORE
        ]
        scored.sort(
            key=lambda item: (
                item[1],
                item[0].updated_at or "",
                item[0].created_at or "",
            ),
            reverse=True,
        )
        return scored[:top_k]

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
        fix_references = self._fix_reference_resolver.resolve(
            FixReferenceResolutionContext(
                store=self._store,
                repository_key=self._repository_key,
                issue=issue,
                similar_records=records,
            )
        )
        cases = tuple(
            sorted(
                (
                    self._case_builder.build(
                        LocalHistoryCaseInput(
                            issue=issue,
                            record=record,
                            score=score,
                            fix_reference=self._fix_reference_for_record(record, fix_references),
                            disposition=self._fix_reference_resolver.disposition(record),
                        )
                    )
                    for record, score in similar
                ),
                key=lambda case: (
                    case.match_score,
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

    def _fix_reference_for_record(
        self,
        record: SonarIssueRecord,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalFixReference | None:
        return self._fix_reference_resolver.find_for_record(record, fix_references)
