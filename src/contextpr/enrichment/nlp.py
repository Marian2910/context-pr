from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from contextpr.enrichment.guidance import GuidanceBuilder
from contextpr.enrichment.history import CombinedHistoricalContext, HistoricalContext
from contextpr.enrichment.intent import (
    CommentIntent,
    comment_intent,
    has_fix_signal,
    history_driven_intent_for,
    should_defer_from_history,
    should_fix_from_history,
    should_fix_local_code_smell,
    should_mark_history_recurrence,
    uses_history_for_guidance,
    uses_non_local_history,
)
from contextpr.enrichment.language_profile import (
    IssueLanguageProfile,
    content_terms,
    is_behavior_risk,
    is_self_explanatory,
    issue_language_profile,
    self_explanatory_score,
)
from contextpr.enrichment.messages import DeterministicGuidanceMessageService
from contextpr.enrichment.models import (
    DeveloperGuidance as DeveloperGuidance,
)
from contextpr.enrichment.models import (
    GuidanceLevel as GuidanceLevel,
)
from contextpr.enrichment.models import (
    IssueEnrichment as IssueEnrichment,
)
from contextpr.enrichment.retrievers import (
    HistoryRetrieverSet,
    actionable_or_none,
    active_history,
    active_source,
    build_history_retriever,
    retrieved_context,
)
from contextpr.enrichment.signals import (
    ContextSignals,
    context_signals,
    fix_tendency_high,
    has_actionable_history,
    has_grounded_history,
    persistence_high,
    quick_fix_tendency_high,
    small_effort,
)
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore


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
        self._message_service = DeterministicGuidanceMessageService()
        self._guidance_builder = GuidanceBuilder(self._message_service)
        self._history_retrievers = HistoryRetrieverSet.build(
            dataset_path,
            enable_local_history=enable_local_history,
            enable_local_git_history=enable_local_git_history,
            history_store=history_store,
            repository_key=repository_key,
        )

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        if self._history_retrievers.requires_configured_local_store():
            raise NotImplementedError(
                "Local repository history mode requires a configured repository store."
            )

        historical_context = self._historical_context(issue)
        active_context = self._active_history(historical_context)
        active_context_source = self._active_source(historical_context)
        language_profile = self._issue_language_profile(issue, active_context)
        signals = self._context_signals(
            issue,
            active_context,
            active_context_source,
            language_profile,
        )
        intent = self._comment_intent(issue, signals)
        if intent is CommentIntent.NONE:
            return None

        guidance = self._build_guidance(
            issue,
            intent,
            signals,
            active_context,
            active_context_source,
        )
        return IssueEnrichment(guidance=guidance, historical_context=historical_context)

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]:
        return {issue.key: self.enrich(issue) for issue in issues}

    def _historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        return self._history_retrievers.historical_context(issue)

    def _retrieved_context(
        self,
        retriever: object,
        issue: SonarIssue,
    ) -> HistoricalContext | None:
        return retrieved_context(retriever, issue)

    @staticmethod
    def _active_history(
        historical_context: CombinedHistoricalContext | None,
    ) -> HistoricalContext | None:
        return active_history(historical_context)

    @staticmethod
    def _active_source(historical_context: CombinedHistoricalContext | None) -> str | None:
        return active_source(historical_context)

    @staticmethod
    def _actionable_or_none(
        historical_context: HistoricalContext | None,
    ) -> HistoricalContext | None:
        return actionable_or_none(historical_context)

    def _build_guidance(
        self,
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        return self._guidance_builder.build_guidance(
            issue,
            comment_intent,
            context_signals,
            historical_context,
            history_source,
        )

    def _context_signals(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
        history_source: str | None,
        language_profile: IssueLanguageProfile,
    ) -> ContextSignals:
        return context_signals(issue, historical_context, history_source, language_profile)

    def _comment_intent(
        self,
        issue: SonarIssue,
        context_signals: ContextSignals,
    ) -> CommentIntent:
        return comment_intent(issue, context_signals)

    @staticmethod
    def _should_fix_local_code_smell(
        issue: SonarIssue,
        context_signals: ContextSignals,
    ) -> bool:
        return should_fix_local_code_smell(issue, context_signals)

    @staticmethod
    def _has_fix_signal(context_signals: ContextSignals) -> bool:
        return has_fix_signal(context_signals)

    @staticmethod
    def _uses_non_local_history(context_signals: ContextSignals) -> bool:
        return uses_non_local_history(context_signals)

    @classmethod
    def _history_driven_intent(
        cls,
        context_signals: ContextSignals,
    ) -> CommentIntent | None:
        _ = cls
        return history_driven_intent_for(context_signals)

    @classmethod
    def _should_defer_from_history(cls, context_signals: ContextSignals) -> bool:
        _ = cls
        return should_defer_from_history(context_signals)

    @classmethod
    def _should_fix_from_history(cls, context_signals: ContextSignals) -> bool:
        _ = cls
        return should_fix_from_history(context_signals)

    @classmethod
    def _should_mark_history_recurrence(
        cls,
        context_signals: ContextSignals,
    ) -> bool:
        _ = cls
        return should_mark_history_recurrence(context_signals)

    @classmethod
    def _uses_history_for_guidance(cls, context_signals: ContextSignals) -> bool:
        _ = cls
        return uses_history_for_guidance(context_signals)

    def _issue_language_profile(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
    ) -> IssueLanguageProfile:
        return issue_language_profile(issue, historical_context)

    @staticmethod
    def _content_terms(*values: str) -> tuple[str, ...]:
        return content_terms(*values)

    @staticmethod
    def _self_explanatory_score(
        issue: SonarIssue,
        content_terms: tuple[str, ...],
    ) -> float:
        return self_explanatory_score(issue, content_terms)

    @staticmethod
    def _small_effort(effort: str | None) -> bool:
        return small_effort(effort)

    @staticmethod
    def _fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
        return fix_tendency_high(historical_context)

    @staticmethod
    def _quick_fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
        return quick_fix_tendency_high(historical_context)

    @staticmethod
    def _persistence_high(historical_context: HistoricalContext | None) -> bool:
        return persistence_high(historical_context)

    @staticmethod
    def _is_self_explanatory(
        issue: SonarIssue,
        language_profile: IssueLanguageProfile,
    ) -> bool:
        return is_self_explanatory(issue, language_profile)

    @staticmethod
    def _is_behavior_risk(
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
        language_profile: IssueLanguageProfile,
    ) -> bool:
        return is_behavior_risk(issue, historical_context, language_profile)

    @staticmethod
    def _build_history_retriever(
        retriever_factory: Callable[[HistoryStore, str], object],
        *,
        enable_local_history: bool,
        history_store: HistoryStore | None,
        repository_key: str | None,
    ) -> object | None:
        return build_history_retriever(
            retriever_factory,
            enable_local_history=enable_local_history,
            history_store=history_store,
            repository_key=repository_key,
        )

    @staticmethod
    def _detailed_guidance(
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        return GuidanceBuilder(DeterministicGuidanceMessageService())._detailed_guidance(
            issue,
            comment_intent,
            context_signals,
            historical_context,
            history_source,
        )

    @staticmethod
    def _contextual_guidance(
        issue: SonarIssue,
        comment_intent: CommentIntent,
        context_signals: ContextSignals,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance:
        return GuidanceBuilder(DeterministicGuidanceMessageService())._contextual_guidance(
            issue,
            comment_intent,
            context_signals,
            historical_context,
            history_source,
        )

    @staticmethod
    def _has_grounded_history(historical_context: HistoricalContext | None) -> bool:
        return has_grounded_history(historical_context)

    @staticmethod
    def _has_actionable_history(historical_context: HistoricalContext | None) -> bool:
        return has_actionable_history(historical_context)
