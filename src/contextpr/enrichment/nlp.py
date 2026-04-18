from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from contextpr.enrichment.history import HistoricalContext, IssueHistoryRetriever
from contextpr.enrichment.intent import IntentClassifier, IntentPrediction
from contextpr.models import SonarIssue


@dataclass(frozen=True, slots=True)
class DeveloperGuidance:
    summary: str
    explanation: str
    next_step: str
    evidence_note: str | None = None


@dataclass(frozen=True, slots=True)
class IssueEnrichment:
    guidance: DeveloperGuidance
    intent_prediction: IntentPrediction | None
    historical_context: HistoricalContext | None


class IssueEnricher:

    def __init__(self, model_path: Path, dataset_path: Path) -> None:
        self._intent_classifier = IntentClassifier(model_path)
        self._history_retriever = IssueHistoryRetriever(dataset_path)

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        intent_prediction = self._intent_classifier.predict(issue)
        historical_context = self._history_retriever.find_context(issue)
        guidance = self._build_guidance(issue, intent_prediction, historical_context)
        if guidance is None:
            return None

        return IssueEnrichment(
            guidance=guidance,
            intent_prediction=intent_prediction,
            historical_context=historical_context,
        )

    def _build_guidance(
        self,
        issue: SonarIssue,
        intent_prediction: IntentPrediction | None,
        historical_context: HistoricalContext | None,
    ) -> DeveloperGuidance | None:
        summary = self._build_summary(issue)
        explanation = self._build_explanation(issue, intent_prediction, historical_context)
        next_step = self._build_next_step(issue)
        evidence_note = self._build_evidence_note(issue, intent_prediction, historical_context)
        if not summary and not explanation and not next_step and evidence_note is None:
            return None

        return DeveloperGuidance(
            summary=summary,
            explanation=explanation,
            next_step=next_step,
            evidence_note=evidence_note,
        )

    def _build_summary(self, issue: SonarIssue) -> str:
        message = issue.message.lower()
        if issue.rule == "python:S3923" or "not all the same" in message:
            return (
                "Sonar flagged this because all branches of the condition appear "
                "to do the same thing."
            )
        if "unused function parameter" in message:
            return "Sonar flagged this because one of the function parameters appears to be unused."
        if "unused local variable" in message:
            return "Sonar flagged this because a local variable appears to be unused."
        if "duplicating this literal" in message:
            return "Sonar flagged this because the same literal is repeated in multiple places."
        if "function is empty" in message or issue.rule == "python:S1186":
            return "Sonar flagged this because the function body is empty without clear intent."
        if issue.issue_type == "BUG":
            return "Sonar flagged this because the code may not behave as intended."
        if issue.issue_type == "CODE_SMELL":
            return "Sonar flagged this because the code can likely be simplified or clarified."
        return f"Sonar flagged this and suggests the code should be reviewed: {issue.message}"

    def _build_explanation(
        self,
        issue: SonarIssue,
        intent_prediction: IntentPrediction | None,
        historical_context: HistoricalContext | None,
    ) -> str:
        issue_kind = self._issue_kind(issue)
        change_kind = self._change_kind(intent_prediction, historical_context, issue_kind)
        if change_kind == "behavior":
            return "This looks more like a behavior issue than a simple cleanup."
        if change_kind == "supporting":
            return (
                "This looks like a small follow-up around the flagged code rather than a large "
                "logic change."
            )
        if issue_kind == "correctness":
            return "This is worth checking carefully because it may affect behavior."
        return "This looks like a cleanup issue rather than a functional change."

    def _build_next_step(self, issue: SonarIssue) -> str:
        message = issue.message.lower()
        if issue.rule == "python:S3923" or "not all the same" in message:
            return (
                "A good next step is to simplify the condition or remove duplicated "
                "branches if they are truly equivalent."
            )
        if "unused function parameter" in message:
            return (
                "A good next step is to remove the unused parameter or rename it in a way "
                "that makes the intent explicit if the signature must stay as-is."
            )
        if "unused local variable" in message:
            return (
                "A good next step is to remove the variable or replace it with `_` "
                "if it is intentional."
            )
        if "duplicating this literal" in message:
            return "A good next step is to extract the repeated literal into a named constant."
        if "function is empty" in message or issue.rule == "python:S1186":
            return (
                "A good next step is to document why the function is intentionally empty "
                "or complete the implementation."
            )
        if issue.issue_type == "BUG":
            return "A good next step is to verify the logic around the flagged code path."
        return "A good next step is to simplify or clarify the flagged code where possible."

    def _build_evidence_note(
        self,
        issue: SonarIssue,
        intent_prediction: IntentPrediction | None,
        historical_context: HistoricalContext | None,
    ) -> str | None:
        if historical_context is None or historical_context.sample_size < 5:
            return None

        change_kind = self._change_kind(
            intent_prediction,
            historical_context,
            self._issue_kind(issue),
        )
        if change_kind == "cleanup":
            return "Similar cases were usually resolved with cleanup around the flagged code."
        if change_kind == "behavior":
            return "Similar cases were more often handled as behavior-oriented fixes."
        if change_kind == "supporting":
            return (
                "Similar cases often came with follow-up updates around tests, documentation, "
                "or nearby code cleanup."
            )
        return None

    @staticmethod
    def _issue_kind(issue: SonarIssue) -> str:
        message = issue.message.lower()
        if issue.issue_type == "BUG":
            return "correctness"
        if (
            "unused" in message
            or "duplicating this literal" in message
            or "not all the same" in message
        ):
            return "cleanup"
        if issue.tags and any(tag in {"design", "unused", "suspicious"} for tag in issue.tags):
            return "cleanup"
        return "general"

    def _change_kind(
        self,
        intent_prediction: IntentPrediction | None,
        historical_context: HistoricalContext | None,
        issue_kind: str,
    ) -> str:
        if issue_kind == "correctness":
            return "behavior"
        if issue_kind == "cleanup":
            return "cleanup"

        label_scores = self._label_scores(intent_prediction, historical_context)
        if (
            label_scores["behavior"] > label_scores["cleanup"]
            and label_scores["behavior"] >= label_scores["supporting"]
        ):
            return "behavior"
        if (
            label_scores["supporting"] > label_scores["cleanup"]
            and label_scores["supporting"] >= label_scores["behavior"]
        ):
            return "supporting"
        return "cleanup"

    @staticmethod
    def _label_scores(
        intent_prediction: IntentPrediction | None,
        historical_context: HistoricalContext | None,
    ) -> dict[str, float]:
        scores = {"cleanup": 0.0, "behavior": 0.0, "supporting": 0.0}
        if intent_prediction is not None:
            scores[IssueEnricher._bucket_for_label(intent_prediction.label)] += (
                intent_prediction.confidence or 0.5
            )
        if historical_context is not None and historical_context.sample_size > 0:
            for label, count in historical_context.label_distribution:
                scores[IssueEnricher._bucket_for_label(label)] += (
                    count / historical_context.sample_size
                )
        return scores

    @staticmethod
    def _bucket_for_label(label: str) -> str:
        normalized = label.strip().lower()
        if normalized in {"fix", "feat", "perf"}:
            return "behavior"
        if normalized in {"docs", "test", "build", "ci"}:
            return "supporting"
        return "cleanup"
