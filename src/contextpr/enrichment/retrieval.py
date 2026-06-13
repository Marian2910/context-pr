from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from contextpr.enrichment.history import CombinedHistoricalContext, HistoricalEvidenceSummary
from contextpr.enrichment.history.dataset import DatasetHistoryRetriever
from contextpr.enrichment.history.local.sonar import LocalSonarHistoryRetriever
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore


class CaseHistoryRetriever(Protocol):
    def find_context(self, issue: SonarIssue) -> HistoricalEvidenceSummary | None: ...


@dataclass(frozen=True, slots=True)
class EnrichmentContext:
    dataset_path: Path | None = None
    enable_local_history: bool = False
    enable_local_git_history: bool = True
    history_store: HistoryStore | None = None
    repository_key: str | None = None


class HistoricalContextRetriever:
    def __init__(self, context: EnrichmentContext) -> None:
        self._context = context
        _ = context.enable_local_git_history
        self._dataset_retriever = self._build_dataset_retriever(context.dataset_path)
        self._local_history_retriever = self._build_local_history_retriever(context)

    def retrieve(self, issue: SonarIssue) -> CombinedHistoricalContext:
        local_sonar = None
        if self._context.enable_local_history:
            local_retriever = self._local_history_retriever
            if local_retriever is None:
                raise NotImplementedError(
                    "Local repository history mode requires a configured repository store."
                )
            local_sonar = local_retriever.find_context(issue)

        dataset = None
        if local_sonar is None and self._dataset_retriever is not None:
            dataset = self._dataset_retriever.find_context(issue)

        return CombinedHistoricalContext(local_sonar=local_sonar, dataset=dataset)

    @staticmethod
    def _build_local_history_retriever(
        context: EnrichmentContext,
    ) -> CaseHistoryRetriever | None:
        if (
            not context.enable_local_history
            or context.history_store is None
            or context.repository_key is None
        ):
            return None
        return LocalSonarHistoryRetriever(context.history_store, context.repository_key)

    @staticmethod
    def _build_dataset_retriever(dataset_path: Path | None) -> CaseHistoryRetriever | None:
        if dataset_path is None or not dataset_path.is_file():
            return None
        return DatasetHistoryRetriever(dataset_path)
