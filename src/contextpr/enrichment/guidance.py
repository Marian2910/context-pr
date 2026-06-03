from __future__ import annotations

from contextpr.enrichment.history import HistoricalContext
from contextpr.enrichment.intent import CommentIntent
from contextpr.enrichment.messages import DeterministicGuidanceMessageService
from contextpr.enrichment.models import DeveloperGuidance, GuidanceLevel
from contextpr.enrichment.signals import ContextSignals
from contextpr.models import SonarIssue


class GuidanceBuilder:
    def __init__(self, message_service: DeterministicGuidanceMessageService) -> None:
        self._message_service = message_service

    def build_guidance(
        self,
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        if comment_intent is CommentIntent.INSPECT_BEFORE_CHANGING:
            return self._detailed_guidance(
                issue,
                comment_intent,
                context_signals,
                historical_context,
                history_source,
            )

        return self._contextual_guidance(
            issue,
            comment_intent,
            context_signals,
            historical_context,
            history_source,
        )

    def _detailed_guidance(
        self,
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        return DeveloperGuidance(
            level=GuidanceLevel.DETAILED,
            explanation=(
                None
                if issue.issue_type == "CODE_SMELL"
                else self._message_service.build_explanation(
                    issue,
                    context_signals,
                    historical_context,
                    history_source,
                )
            ),
            next_step=self._message_service.build_next_step(
                comment_intent.value,
                context_signals,
                historical_context,
                history_source,
            ),
            evidence_note=self._message_service.build_evidence_note(
                issue,
                comment_intent.value,
                context_signals,
                historical_context,
                history_source,
            ),
        )

    def _contextual_guidance(
        self,
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        return DeveloperGuidance(
            level=(
                GuidanceLevel.MINIMAL
                if context_signals.self_explanatory
                else GuidanceLevel.CONTEXTUAL
            ),
            evidence_note=self._message_service.build_evidence_note(
                issue,
                comment_intent.value,
                context_signals,
                historical_context,
                history_source,
            ),
        )
