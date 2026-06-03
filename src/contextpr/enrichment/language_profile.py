from __future__ import annotations

from dataclasses import dataclass

from contextpr.enrichment.history import HistoricalContext
from contextpr.enrichment.nlp_constants import (
    AMBIGUITY_MARKERS,
    BEHAVIOR_RULES,
    SELF_EXPLANATORY_RULES,
    STOP_TOKENS,
    TOKEN_PATTERN,
)
from contextpr.models import SonarIssue


@dataclass(frozen=True, slots=True)
class IssueLanguageProfile:
    content_terms: tuple[str, ...]
    ambiguity_markers: tuple[str, ...]
    self_explanatory_score: float
    history_anchor_terms: tuple[str, ...]


def issue_language_profile(
    issue: SonarIssue,
    historical_context: HistoricalContext | None,
) -> IssueLanguageProfile:
    terms = content_terms(issue.message, issue.location.path)
    ambiguity_markers = tuple(term for term in terms if term in AMBIGUITY_MARKERS)
    score = self_explanatory_score(issue, terms)
    history_anchor_terms = (
        historical_context.salient_terms if historical_context is not None else ()
    )
    return IssueLanguageProfile(
        content_terms=terms,
        ambiguity_markers=ambiguity_markers,
        self_explanatory_score=score,
        history_anchor_terms=history_anchor_terms,
    )


def content_terms(*values: str) -> tuple[str, ...]:
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


def self_explanatory_score(issue: SonarIssue, terms: tuple[str, ...]) -> float:
    score = 0.0
    term_set = set(terms)
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


def is_self_explanatory(
    issue: SonarIssue,
    language_profile: IssueLanguageProfile,
) -> bool:
    _ = issue
    return language_profile.self_explanatory_score >= 0.75


def is_behavior_risk(
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
