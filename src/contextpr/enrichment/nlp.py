from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from contextpr.enrichment.history import (
    CombinedHistoricalContext,
    GlobalDatasetHistoryRetriever,
    HistoricalContext,
    LocalGitHistoryRetriever,
    LocalPullRequestHistoryRetriever,
    LocalReviewCommentHistoryRetriever,
    LocalSonarHistoryRetriever,
)
from contextpr.enrichment.messages import DeterministicGuidanceMessageService
from contextpr.enrichment.nlp_constants import (
    AMBIGUITY_MARKERS,
    BEHAVIOR_RULES,
    HOTSPOT_FILE_MATCHES,
    HOTSPOT_MODULE_MATCHES,
    HOTSPOT_MODULE_SHARE,
    MIN_HISTORY_SAMPLE_SIZE,
    MIN_HISTORY_SHARE,
    MIN_STRONG_HISTORY_MATCHES,
    SELF_EXPLANATORY_RULES,
    STOP_TOKENS,
    TOKEN_PATTERN,
)
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore


class GuidanceLevel(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    CONTEXTUAL = "contextual"
    DETAILED = "detailed"


class CommentIntent(StrEnum):
    NONE = "none"
    WORTH_FIXING_NOW = "worth_fixing_now"
    INSPECT_BEFORE_CHANGING = "inspect_before_changing"
    DECIDE_BEFORE_DEFERRING = "decide_before_deferring"
    RECURS_HERE = "recurs_here"


@dataclass(frozen=True, slots=True)
class DeveloperGuidance:
    level: GuidanceLevel
    explanation: str | None = None
    next_step: str | None = None
    evidence_note: str | None = None


@dataclass(frozen=True, slots=True)
class IssueEnrichment:
    guidance: DeveloperGuidance
    historical_context: CombinedHistoricalContext | None


@dataclass(frozen=True, slots=True)
class IssueLanguageProfile:
    content_terms: tuple[str, ...]
    ambiguity_markers: tuple[str, ...]
    self_explanatory_score: float
    history_anchor_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextSignals:
    source_is_local: bool
    self_explanatory: bool
    behavior_risk: bool
    local_recurrence: bool
    same_file_recurrence: bool
    same_module_recurrence: bool
    fix_tendency_high: bool
    quick_fix_tendency_high: bool
    persistence_high: bool
    small_effort: bool
    strong_history: bool


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
        self._enable_local_history = enable_local_history
        self._dataset_history_retriever = (
            GlobalDatasetHistoryRetriever(dataset_path)
            if dataset_path is not None
            else None
        )
        self._local_history_retriever = self._build_history_retriever(
            LocalSonarHistoryRetriever,
            enable_local_history=enable_local_history,
            history_store=history_store,
            repository_key=repository_key,
        )
        self._local_git_history_retriever = self._build_history_retriever(
            LocalGitHistoryRetriever,
            enable_local_history=enable_local_history and enable_local_git_history,
            history_store=history_store,
            repository_key=repository_key,
        )
        self._local_pr_history_retriever = self._build_history_retriever(
            LocalPullRequestHistoryRetriever,
            enable_local_history=enable_local_history,
            history_store=history_store,
            repository_key=repository_key,
        )
        self._local_review_comment_history_retriever = self._build_history_retriever(
            LocalReviewCommentHistoryRetriever,
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
        active_history = self._active_history(historical_context)
        active_source = self._active_source(historical_context)
        language_profile = self._issue_language_profile(issue, active_history)
        context_signals = self._context_signals(
            issue,
            active_history,
            active_source,
            language_profile,
        )
        comment_intent = self._comment_intent(issue, context_signals)
        if comment_intent is CommentIntent.NONE:
            return None

        guidance = self._build_guidance(
            issue,
            comment_intent,
            context_signals,
            active_history,
            active_source,
        )
        return IssueEnrichment(guidance=guidance, historical_context=historical_context)

    def _historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        global_dataset_context = self._retrieved_context(self._dataset_history_retriever, issue)
        if not self._enable_local_history:
            return CombinedHistoricalContext(global_dataset=global_dataset_context)

        return CombinedHistoricalContext(
            local_sonar=self._retrieved_context(self._local_history_retriever, issue),
            local_git=self._retrieved_context(self._local_git_history_retriever, issue),
            local_prs=self._retrieved_context(self._local_pr_history_retriever, issue),
            local_review_comments=self._retrieved_context(
                self._local_review_comment_history_retriever,
                issue,
            ),
        )

    def _retrieved_context(
        self,
        retriever: object,
        issue: SonarIssue,
    ) -> HistoricalContext | None:
        if retriever is None:
            return None

        find_context = getattr(retriever, "find_context")
        return self._actionable_or_none(find_context(issue))

    @staticmethod
    def _active_history(
        historical_context: CombinedHistoricalContext | None,
    ) -> HistoricalContext | None:
        if historical_context is None:
            return None
        return historical_context.preferred_evidence()

    @staticmethod
    def _active_source(historical_context: CombinedHistoricalContext | None) -> str | None:
        if historical_context is None:
            return None
        return historical_context.preferred_source_name()

    @staticmethod
    def _actionable_or_none(
        historical_context: HistoricalContext | None,
    ) -> HistoricalContext | None:
        if not IssueEnricher._has_actionable_history(historical_context):
            return None
        return historical_context

    def _build_guidance(
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

    def _context_signals(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
        history_source: str | None,
        language_profile: IssueLanguageProfile,
    ) -> ContextSignals:
        source_is_local = self._message_service.is_local_history_source(history_source)
        self_explanatory = self._is_self_explanatory(issue, language_profile)
        behavior_risk = self._is_behavior_risk(issue, historical_context, language_profile)
        strong_history = self._has_actionable_history(historical_context)
        same_file_recurrence = (
            historical_context is not None
            and historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES
        )
        same_module_recurrence = (
            historical_context is not None
            and historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
            and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
        )
        local_recurrence = source_is_local and (same_file_recurrence or same_module_recurrence)
        fix_tendency_high = self._fix_tendency_high(historical_context)
        quick_fix_tendency_high = self._quick_fix_tendency_high(historical_context)
        persistence_high = self._persistence_high(historical_context)
        small_effort = self._small_effort(issue.effort)
        return ContextSignals(
            source_is_local=source_is_local,
            self_explanatory=self_explanatory,
            behavior_risk=behavior_risk,
            local_recurrence=local_recurrence,
            same_file_recurrence=same_file_recurrence,
            same_module_recurrence=same_module_recurrence,
            fix_tendency_high=fix_tendency_high,
            quick_fix_tendency_high=quick_fix_tendency_high,
            persistence_high=persistence_high,
            small_effort=small_effort,
            strong_history=strong_history,
        )

    def _comment_intent(
        self,
        issue: SonarIssue,
        context_signals: ContextSignals,
    ) -> CommentIntent:
        if context_signals.behavior_risk:
            return CommentIntent.INSPECT_BEFORE_CHANGING

        if context_signals.self_explanatory and not context_signals.local_recurrence:
            return CommentIntent.NONE

        if self._should_fix_local_code_smell(issue, context_signals):
            return CommentIntent.WORTH_FIXING_NOW

        history_driven_intent = self._history_driven_intent(context_signals)
        if history_driven_intent is not None:
            return history_driven_intent

        return CommentIntent.NONE

    @staticmethod
    def _should_fix_local_code_smell(
        issue: SonarIssue,
        context_signals: ContextSignals,
    ) -> bool:
        return (
            issue.issue_type == "CODE_SMELL"
            and not context_signals.self_explanatory
            and context_signals.source_is_local
            and context_signals.fix_tendency_high
        )

    @staticmethod
    def _has_fix_signal(context_signals: ContextSignals) -> bool:
        return (
            context_signals.fix_tendency_high
            or context_signals.quick_fix_tendency_high
            or context_signals.small_effort
        )

    @staticmethod
    def _uses_non_local_history(context_signals: ContextSignals) -> bool:
        return not context_signals.source_is_local and context_signals.strong_history

    @classmethod
    def _history_driven_intent(
        cls,
        context_signals: ContextSignals,
    ) -> CommentIntent | None:
        if cls._should_defer_from_history(context_signals):
            return CommentIntent.DECIDE_BEFORE_DEFERRING
        if cls._should_fix_from_history(context_signals):
            return CommentIntent.WORTH_FIXING_NOW
        if cls._should_mark_history_recurrence(context_signals):
            return CommentIntent.RECURS_HERE
        return None

    @classmethod
    def _should_defer_from_history(cls, context_signals: ContextSignals) -> bool:
        return cls._uses_history_for_guidance(context_signals) and context_signals.persistence_high

    @classmethod
    def _should_fix_from_history(cls, context_signals: ContextSignals) -> bool:
        return cls._uses_history_for_guidance(context_signals) and cls._has_fix_signal(
            context_signals
        )

    @classmethod
    def _should_mark_history_recurrence(
        cls,
        context_signals: ContextSignals,
    ) -> bool:
        return (
            cls._uses_history_for_guidance(context_signals)
            and not context_signals.self_explanatory
        )

    @classmethod
    def _uses_history_for_guidance(cls, context_signals: ContextSignals) -> bool:
        return context_signals.local_recurrence or cls._uses_non_local_history(context_signals)

    def _issue_language_profile(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
    ) -> IssueLanguageProfile:
        content_terms = self._content_terms(issue.message, issue.location.path)
        ambiguity_markers = tuple(
            term for term in content_terms if term in AMBIGUITY_MARKERS
        )
        self_explanatory_score = self._self_explanatory_score(issue, content_terms)
        history_anchor_terms = historical_context.salient_terms if historical_context is not None else ()
        return IssueLanguageProfile(
            content_terms=content_terms,
            ambiguity_markers=ambiguity_markers,
            self_explanatory_score=self_explanatory_score,
            history_anchor_terms=history_anchor_terms,
        )

    @staticmethod
    def _content_terms(*values: str) -> tuple[str, ...]:
        terms: list[str] = []
        for value in values:
            for token in TOKEN_PATTERN.findall(value.lower()):
                if len(token) <= 2 or token in STOP_TOKENS or token.isdigit():
                    continue
                terms.append(token)
        seen: dict[str, None] = {}
        for term in terms:
            seen.setdefault(term, None)
        return tuple(seen)

    @staticmethod
    def _self_explanatory_score(issue: SonarIssue, content_terms: tuple[str, ...]) -> float:
        score = 0.0
        term_set = set(content_terms)
        if {"unused", "parameter"} <= term_set:
            score += 0.5
        if {"unused", "variable"} <= term_set:
            score += 0.5
        if {"literal", "duplicating"} <= term_set or {"literal", "constant"} <= term_set:
            score += 0.6
        if {"empty", "function"} <= term_set:
            score += 0.5
        if issue.rule in SELF_EXPLANATORY_RULES:
            score += 0.35
        if issue.issue_type == "CODE_SMELL":
            score += 0.15
        return min(score, 1.0)

    @staticmethod
    def _small_effort(effort: str | None) -> bool:
        if effort is None:
            return False
        digits = "".join(char for char in effort if char.isdigit())
        if not digits:
            return False
        return int(digits) <= 10

    @staticmethod
    def _fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None:
            return False
        if historical_context.resolved_share >= 0.6:
            return True
        return (
            historical_context.dominant_disposition == "resolved"
            and historical_context.dominant_disposition_share >= 0.6
        )

    @staticmethod
    def _quick_fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None:
            return False
        if historical_context.quick_fix_share >= 0.5:
            return True
        if historical_context.median_resolution_days is None:
            return False
        return historical_context.median_resolution_days <= 7

    @staticmethod
    def _persistence_high(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None:
            return False
        if historical_context.persistent_share >= 0.6 or historical_context.accepted_share >= 0.5:
            return True
        return (
            historical_context.dominant_disposition in {"persistent", "accepted"}
            and historical_context.dominant_disposition_share >= 0.6
        )

    @staticmethod
    def _is_self_explanatory(
        issue: SonarIssue,
        language_profile: IssueLanguageProfile,
    ) -> bool:
        return language_profile.self_explanatory_score >= 0.75

    @staticmethod
    def _is_behavior_risk(
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
        language_profile: IssueLanguageProfile,
    ) -> bool:
        _ = historical_context
        if issue.issue_type == "BUG" or issue.rule in BEHAVIOR_RULES:
            return True
        if language_profile.ambiguity_markers:
            return True
        return False

    @staticmethod
    def _build_history_retriever(
        retriever_factory: Callable[[HistoryStore, str], object],
        *,
        enable_local_history: bool,
        history_store: HistoryStore | None,
        repository_key: str | None,
    ) -> object | None:
        if not enable_local_history or history_store is None or repository_key is None:
            return None
        return retriever_factory(history_store, repository_key)

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

    @staticmethod
    def _has_grounded_history(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None or historical_context.sample_size < MIN_HISTORY_SAMPLE_SIZE:
            return False

        has_rule_support = historical_context.same_rule_matches > 0
        has_local_support = (
            historical_context.same_scope_matches > 0
            or historical_context.same_path_family_matches > 0
        )
        has_consensus = (
            historical_context.dominant_disposition_share >= MIN_HISTORY_SHARE
            or historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        )
        has_strong_matches = historical_context.strong_match_count >= MIN_STRONG_HISTORY_MATCHES
        return has_rule_support and has_local_support and has_consensus and has_strong_matches

    @staticmethod
    def _has_actionable_history(historical_context: HistoricalContext | None) -> bool:
        if not IssueEnricher._has_grounded_history(historical_context):
            return False

        assert historical_context is not None
        if historical_context.fix_references:
            return True
        if historical_context.dominant_disposition is not None:
            return True
        if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
            return True
        if (
            historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
            and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
        ):
            return True
        return False
