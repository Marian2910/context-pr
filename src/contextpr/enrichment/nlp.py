from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from contextpr.enrichment.history import HistoricalContext, IssueHistoryRetriever
from contextpr.enrichment.intent import IntentClassifier, IntentPrediction
from contextpr.models import SonarIssue


@dataclass(frozen=True, slots=True)
class IssueEnrichment:

    quality_context: str | None
    intent_prediction: IntentPrediction | None
    historical_context: HistoricalContext | None


class IssueEnricher:

    def __init__(self, model_path: Path, dataset_path: Path) -> None:
        self._intent_classifier = IntentClassifier(model_path)
        self._history_retriever = IssueHistoryRetriever(dataset_path)

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        intent_prediction = self._intent_classifier.predict(issue)
        historical_context = self._history_retriever.find_context(issue)
        quality_context = self._quality_context(issue)

        if (
            intent_prediction is None
            and historical_context is None
            and quality_context is None
        ):
            return None

        return IssueEnrichment(
            quality_context=quality_context,
            intent_prediction=intent_prediction,
            historical_context=historical_context,
        )

    @staticmethod
    def _quality_context(issue: SonarIssue) -> str | None:
        parts = [
            part
            for part in (
                issue.clean_code_attribute,
                issue.clean_code_attribute_category,
            )
            if part
        ]
        if parts:
            return " / ".join(parts)
        if issue.tags:
            return ", ".join(issue.tags[:2])
        if issue.issue_type:
            return issue.issue_type
        return None
