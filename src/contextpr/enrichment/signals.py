from __future__ import annotations

from dataclasses import dataclass

from contextpr.enrichment.history import HistoricalContext
from contextpr.enrichment.language_profile import (
    IssueLanguageProfile,
    is_behavior_risk,
    is_self_explanatory,
)
from contextpr.enrichment.messages import DeterministicGuidanceMessageService
from contextpr.enrichment.nlp_constants import (
    HOTSPOT_FILE_MATCHES,
    HOTSPOT_MODULE_MATCHES,
    HOTSPOT_MODULE_SHARE,
    MIN_HISTORY_SAMPLE_SIZE,
    MIN_HISTORY_SHARE,
    MIN_STRONG_HISTORY_MATCHES,
)
from contextpr.models import SonarIssue


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


def context_signals(
    issue: SonarIssue,
    historical_context: HistoricalContext | None,
    history_source: str | None,
    language_profile: IssueLanguageProfile,
) -> ContextSignals:
    source_is_local = DeterministicGuidanceMessageService.is_local_history_source(
        history_source
    )
    self_explanatory = is_self_explanatory(issue, language_profile)
    behavior_risk = is_behavior_risk(issue, historical_context, language_profile)
    strong_history = has_actionable_history(historical_context)
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
    return ContextSignals(
        source_is_local=source_is_local,
        self_explanatory=self_explanatory,
        behavior_risk=behavior_risk,
        local_recurrence=local_recurrence,
        same_file_recurrence=same_file_recurrence,
        same_module_recurrence=same_module_recurrence,
        fix_tendency_high=fix_tendency_high(historical_context),
        quick_fix_tendency_high=quick_fix_tendency_high(historical_context),
        persistence_high=persistence_high(historical_context),
        small_effort=small_effort(issue.effort),
        strong_history=strong_history,
    )


def small_effort(effort: str | None) -> bool:
    if effort is None:
        return False
    digits = "".join(char for char in effort if char.isdigit())
    if not digits:
        return False
    return int(digits) <= 10


def fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
    if historical_context is None:
        return False
    if historical_context.resolved_share >= 0.6:
        return True
    return (
        historical_context.dominant_disposition == "resolved"
        and historical_context.dominant_disposition_share >= 0.6
    )


def quick_fix_tendency_high(historical_context: HistoricalContext | None) -> bool:
    if historical_context is None:
        return False
    if historical_context.quick_fix_share >= 0.5:
        return True
    if historical_context.median_resolution_days is None:
        return False
    return historical_context.median_resolution_days <= 7


def persistence_high(historical_context: HistoricalContext | None) -> bool:
    if historical_context is None:
        return False
    if historical_context.persistent_share >= 0.6 or historical_context.accepted_share >= 0.5:
        return True
    return (
        historical_context.dominant_disposition in {"persistent", "accepted"}
        and historical_context.dominant_disposition_share >= 0.6
    )


def has_grounded_history(historical_context: HistoricalContext | None) -> bool:
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


def has_actionable_history(historical_context: HistoricalContext | None) -> bool:
    if not has_grounded_history(historical_context):
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
