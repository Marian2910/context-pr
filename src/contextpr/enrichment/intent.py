from __future__ import annotations

from enum import StrEnum

from contextpr.enrichment.signals import ContextSignals
from contextpr.models import SonarIssue


class CommentIntent(StrEnum):
    NONE = "none"
    WORTH_FIXING_NOW = "worth_fixing_now"
    INSPECT_BEFORE_CHANGING = "inspect_before_changing"
    DECIDE_BEFORE_DEFERRING = "decide_before_deferring"
    RECURS_HERE = "recurs_here"


def comment_intent(
    issue: SonarIssue,
    context_signals: ContextSignals,
) -> CommentIntent:
    if context_signals.behavior_risk:
        return CommentIntent.INSPECT_BEFORE_CHANGING

    if context_signals.self_explanatory and not context_signals.local_recurrence:
        return CommentIntent.NONE

    if should_fix_local_code_smell(issue, context_signals):
        return CommentIntent.WORTH_FIXING_NOW

    history_driven_intent = history_driven_intent_for(context_signals)
    if history_driven_intent is not None:
        return history_driven_intent

    return CommentIntent.NONE


def should_fix_local_code_smell(
    issue: SonarIssue,
    context_signals: ContextSignals,
) -> bool:
    return (
        issue.issue_type == "CODE_SMELL"
        and not context_signals.self_explanatory
        and context_signals.source_is_local
        and context_signals.fix_tendency_high
    )


def has_fix_signal(context_signals: ContextSignals) -> bool:
    return (
        context_signals.fix_tendency_high
        or context_signals.quick_fix_tendency_high
        or context_signals.small_effort
    )


def uses_non_local_history(context_signals: ContextSignals) -> bool:
    return not context_signals.source_is_local and context_signals.strong_history


def history_driven_intent_for(
    context_signals: ContextSignals,
) -> CommentIntent | None:
    if should_defer_from_history(context_signals):
        return CommentIntent.DECIDE_BEFORE_DEFERRING
    if should_fix_from_history(context_signals):
        return CommentIntent.WORTH_FIXING_NOW
    if should_mark_history_recurrence(context_signals):
        return CommentIntent.RECURS_HERE
    return None


def should_defer_from_history(context_signals: ContextSignals) -> bool:
    return uses_history_for_guidance(context_signals) and context_signals.persistence_high


def should_fix_from_history(context_signals: ContextSignals) -> bool:
    return uses_history_for_guidance(context_signals) and has_fix_signal(context_signals)


def should_mark_history_recurrence(
    context_signals: ContextSignals,
) -> bool:
    return uses_history_for_guidance(context_signals) and not context_signals.self_explanatory


def uses_history_for_guidance(context_signals: ContextSignals) -> bool:
    return context_signals.local_recurrence or uses_non_local_history(context_signals)
