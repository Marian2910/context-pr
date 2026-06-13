from __future__ import annotations

from pathlib import Path

from contextpr.enrichment.guidance import (
    DeveloperGuidance,
    GuidanceBuilder,
    GuidanceLevel,
    IssueEnrichment,
)
from contextpr.enrichment.retrieval import EnrichmentContext, HistoricalContextRetriever
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore

__all__ = [
    "DeveloperGuidance",
    "GuidanceLevel",
    "IssueEnricher",
    "IssueEnrichment",
]


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
        self._context_retriever = HistoricalContextRetriever(
            EnrichmentContext(
                dataset_path=dataset_path,
                enable_local_history=enable_local_history,
                enable_local_git_history=enable_local_git_history,
                history_store=history_store,
                repository_key=repository_key,
            )
        )
        self._guidance_builder = GuidanceBuilder()

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        historical_context = self._context_retriever.retrieve(issue)
        guidance = self._guidance_builder.build(issue, historical_context)
        if guidance is None:
            return None
        return IssueEnrichment(guidance=guidance, historical_context=historical_context)

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]:
        return {issue.key: self.enrich(issue) for issue in issues}
