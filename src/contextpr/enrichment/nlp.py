from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from contextpr.enrichment.history.dataset import DatasetHistoryRetriever
from contextpr.enrichment.history import (
    CombinedHistoricalContext,
    EvidenceBackedGuidance,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalIssueCase,
    LocalSonarHistoryRetriever,
)
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore

MIN_ENRICHMENT_CONFIDENCE = 0.70


class CaseHistoryRetriever(Protocol):
    def find_context(self, issue: SonarIssue) -> HistoricalEvidenceSummary | None: ...


class GuidanceLevel(StrEnum):
    NONE = "none"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True, slots=True)
class DeveloperGuidance:
    level: GuidanceLevel
    evidence: EvidenceBackedGuidance


@dataclass(frozen=True, slots=True)
class IssueEnrichment:
    guidance: DeveloperGuidance
    historical_context: CombinedHistoricalContext | None


class IssueEnricher:
    def __init__(
        self,
        dataset_path: Path | None = None,
        *,
        enable_local_history: bool = False,
        enable_local_git_history: bool = True,
        history_store: HistoryStore | None = None,
        repository_key: str | None = None,
    ) -> None:
        _ = enable_local_git_history
        self._enable_local_history = enable_local_history
        self._dataset_retriever = self._build_dataset_retriever(dataset_path)
        self._local_history_retriever: CaseHistoryRetriever | None = self._build_history_retriever(
            LocalSonarHistoryRetriever,
            enable_local_history=enable_local_history,
            history_store=history_store,
            repository_key=repository_key,
        )

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        if self._enable_local_history and self._local_history_retriever is None:
            raise NotImplementedError(
                "Local repository history mode requires a configured repository store."
            )

        historical_context = self._historical_context(issue)
        summary = historical_context.preferred_evidence()
        if summary is None:
            return None

        guidance = self._build_guidance(issue, summary)
        if guidance is None:
            return None
        return IssueEnrichment(guidance=guidance, historical_context=historical_context)

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]:
        return {issue.key: self.enrich(issue) for issue in issues}

    def _historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        local_sonar = None
        if self._enable_local_history and self._local_history_retriever is not None:
            local_sonar = self._local_history_retriever.find_context(issue)

        dataset = None
        if local_sonar is None and self._dataset_retriever is not None:
            dataset = self._dataset_retriever.find_context(issue)

        return CombinedHistoricalContext(local_sonar=local_sonar, dataset=dataset)

    def _build_guidance(
        self,
        issue: SonarIssue,
        summary: HistoricalEvidenceSummary,
    ) -> DeveloperGuidance | None:
        case = summary.best_case()
        if case is None or case.confidence < MIN_ENRICHMENT_CONFIDENCE:
            return None

        evidence = EvidenceBackedGuidance(
            decision=self._decision(case),
            confidence=case.confidence,
            reason=self._reason(issue, summary, case),
            case_type=case.case_type,
            case_key=case.issue_key,
            precedent_url=self._precedent_url(case),
            precedent_pr_number=(
                case.fix_reference.pr_number if case.fix_reference is not None else None
            ),
            precedent_evidence=(
                case.fix_reference.evidence if case.fix_reference is not None else ()
            ),
        )
        return DeveloperGuidance(level=GuidanceLevel.CONTEXTUAL, evidence=evidence)

    @staticmethod
    def _decision(case: HistoricalIssueCase) -> str:
        if case.case_type is HistoricalCaseType.DEFERRED:
            return "safe to defer"
        if case.case_type is HistoricalCaseType.PERSISTENT:
            return "safe to defer"
        if case.case_type is HistoricalCaseType.REVIEW_CAREFULLY:
            return "review carefully"
        return "likely worth fixing now"

    @staticmethod
    def _precedent_url(case: HistoricalIssueCase) -> str | None:
        if case.fix_reference is None:
            return None
        return case.fix_reference.file_url or case.fix_reference.pr_url

    @classmethod
    def _reason(
        cls,
        issue: SonarIssue,
        summary: HistoricalEvidenceSummary,
        case: HistoricalIssueCase,
    ) -> str:
        total = max(summary.close_cases_count, summary.related_cases_count)
        file_suffix = cls._file_suffix(issue, summary)
        history_scope = (
            "cross-project dataset matches"
            if summary.source_name == "dataset"
            else "close historical matches"
        )
        singular_history_scope = (
            "cross-project dataset match"
            if summary.source_name == "dataset"
            else "close historical match"
        )
        if case.case_type is HistoricalCaseType.DEFERRED:
            deferred_count = summary.accepted_cases_count + summary.persistent_cases_count
            return (
                f"{deferred_count} of {total} {history_scope} for `{issue.rule}` "
                f"were accepted or left open{file_suffix}."
            )
        if case.case_type is HistoricalCaseType.PERSISTENT:
            return (
                f"{summary.persistent_cases_count} of {total} {history_scope} for "
                f"`{issue.rule}` remained open{file_suffix}."
            )
        if case.case_type is HistoricalCaseType.REVIEW_CAREFULLY:
            return (
                f"the closest {singular_history_scope} for `{issue.rule}` is behavior-sensitive "
                f"and scored {round(case.confidence * 100)}% confidence{file_suffix}."
            )
        return (
            f"{summary.fixed_cases_count} of {total} {history_scope} for "
            f"`{issue.rule}` were fixed{file_suffix}."
        )

    @staticmethod
    def _file_suffix(issue: SonarIssue, summary: HistoricalEvidenceSummary) -> str:
        if any(case.file_path == issue.location.path for case in summary.cases):
            return ", including one in this file"
        return ""

    @staticmethod
    def _build_history_retriever(
        retriever_factory: Callable[[HistoryStore, str], CaseHistoryRetriever],
        *,
        enable_local_history: bool,
        history_store: HistoryStore | None,
        repository_key: str | None,
    ) -> CaseHistoryRetriever | None:
        if not enable_local_history or history_store is None or repository_key is None:
            return None
        return retriever_factory(history_store, repository_key)

    @staticmethod
    def _build_dataset_retriever(dataset_path: Path | None) -> CaseHistoryRetriever | None:
        if dataset_path is None or not dataset_path.is_file():
            return None
        return DatasetHistoryRetriever(dataset_path)
