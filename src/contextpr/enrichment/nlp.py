from __future__ import annotations

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
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore

MIN_HISTORY_SAMPLE_SIZE = 5
MIN_HISTORY_SHARE = 0.5
MIN_STRONG_HISTORY_MATCHES = 2
HOTSPOT_FILE_MATCHES = 2
HOTSPOT_MODULE_MATCHES = 3
HOTSPOT_MODULE_SHARE = 0.5

PATTERN_BY_RULE = {
    "python:S3923": "structural_simplification",
    "python:S1172": "self_explanatory_cleanup",
    "python:S1481": "self_explanatory_cleanup",
    "python:S1192": "self_explanatory_cleanup",
    "python:S1186": "self_explanatory_cleanup",
    "python:S1515": "behavior_sensitive_cleanup",
}

TRIVIAL_PATTERNS = {"self_explanatory_cleanup"}

DETAILED_PATTERNS = {
    "behavior_risk",
    "behavior_sensitive_cleanup",
}


class GuidanceLevel(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    CONTEXTUAL = "contextual"
    DETAILED = "detailed"


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


class IssueEnricher:
    def __init__(
        self,
        dataset_path: Path,
        *,
        enable_local_history: bool = False,
        enable_local_git_history: bool = True,
        history_store: HistoryStore | None = None,
        repository_key: str | None = None,
    ) -> None:
        self._global_history_retriever = GlobalDatasetHistoryRetriever(dataset_path)
        self._message_service = DeterministicGuidanceMessageService()
        self._enable_local_history = enable_local_history
        self._local_history_retriever = (
            LocalSonarHistoryRetriever(history_store, repository_key)
            if enable_local_history and history_store is not None and repository_key is not None
            else None
        )
        self._local_git_history_retriever = (
            LocalGitHistoryRetriever(history_store, repository_key)
            if (
                enable_local_history
                and enable_local_git_history
                and history_store is not None
                and repository_key is not None
            )
            else None
        )
        self._local_pr_history_retriever = (
            LocalPullRequestHistoryRetriever(history_store, repository_key)
            if enable_local_history and history_store is not None and repository_key is not None
            else None
        )
        self._local_review_comment_history_retriever = (
            LocalReviewCommentHistoryRetriever(history_store, repository_key)
            if enable_local_history and history_store is not None and repository_key is not None
            else None
        )

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        if self._enable_local_history and self._local_history_retriever is None:
            raise NotImplementedError(
                "Local repository history mode requires a configured repository store."
            )

        historical_context = self._historical_context(issue)
        active_history = self._active_history(historical_context)
        active_source = self._active_source(historical_context)
        guidance = self._build_guidance(issue, active_history, active_source)
        if guidance is None:
            return None

        return IssueEnrichment(guidance=guidance, historical_context=historical_context)

    def _historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        if not self._enable_local_history:
            return CombinedHistoricalContext(
                global_dataset=self._actionable_or_none(
                    self._global_history_retriever.find_context(issue)
                )
            )

        local_context = self._local_historical_context(issue)
        if local_context.preferred_source_name() is not None:
            return local_context

        return CombinedHistoricalContext(
            local_sonar=local_context.local_sonar,
            local_git=local_context.local_git,
            local_prs=local_context.local_prs,
            local_review_comments=local_context.local_review_comments,
            global_dataset=self._actionable_or_none(
                self._global_history_retriever.find_context(issue)
            ),
        )

    def _local_historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        return CombinedHistoricalContext(
            local_sonar=self._retrieved_context(self._local_history_retriever, issue),
            local_git=self._retrieved_context(self._local_git_history_retriever, issue),
            local_prs=self._retrieved_context(self._local_pr_history_retriever, issue),
            local_review_comments=self._retrieved_context(
                self._local_review_comment_history_retriever,
                issue,
            ),
            global_dataset=None,
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
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> DeveloperGuidance | None:
        issue_pattern = self._issue_pattern(issue)
        guidance_level = self._guidance_level(
            issue,
            issue_pattern,
            historical_context,
            history_source,
        )
        if guidance_level is GuidanceLevel.NONE:
            return None

        evidence_note = self._build_evidence_note(historical_context, history_source)
        if guidance_level is GuidanceLevel.MINIMAL:
            return DeveloperGuidance(level=guidance_level, evidence_note=evidence_note)

        explanation = self._build_explanation(
            issue,
            issue_pattern,
            historical_context,
            history_source,
        )
        next_step = (
            self._build_next_step(issue, issue_pattern, historical_context, history_source)
            if guidance_level is GuidanceLevel.DETAILED
            else None
        )

        return DeveloperGuidance(
            level=guidance_level,
            explanation=explanation,
            next_step=next_step,
            evidence_note=evidence_note,
        )

    def _issue_pattern(self, issue: SonarIssue) -> str:
        if issue.rule in PATTERN_BY_RULE:
            return PATTERN_BY_RULE[issue.rule]

        message = issue.message.lower()
        if "not all the same" in message:
            return "structural_simplification"
        if "unused function parameter" in message:
            return "self_explanatory_cleanup"
        if "unused local variable" in message:
            return "self_explanatory_cleanup"
        if "duplicating this literal" in message:
            return "self_explanatory_cleanup"
        if "function is empty" in message or issue.rule == "python:S1186":
            return "self_explanatory_cleanup"
        if "lambda" in message and "loop iteration" in message:
            return "behavior_sensitive_cleanup"
        if issue.issue_type == "BUG":
            return "behavior_risk"
        if issue.issue_type == "CODE_SMELL":
            return "cleanup_candidate"
        return "general_review"

    def _guidance_level(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> GuidanceLevel:
        if issue_pattern in TRIVIAL_PATTERNS:
            return (
                GuidanceLevel.MINIMAL
                if self._should_surface_self_explanatory_history(
                    historical_context,
                    history_source,
                )
                else GuidanceLevel.NONE
            )

        if issue_pattern == "structural_simplification":
            return (
                GuidanceLevel.DETAILED
                if self._needs_duplicate_condition_context(historical_context)
                else GuidanceLevel.NONE
            )

        if issue_pattern in DETAILED_PATTERNS or issue.issue_type == "BUG":
            return GuidanceLevel.DETAILED

        if issue.issue_type == "CODE_SMELL":
            return (
                GuidanceLevel.CONTEXTUAL
                if self._should_comment_on_maintainability(
                    historical_context,
                    history_source,
                )
                else GuidanceLevel.NONE
            )

        if self._has_grounded_history(historical_context):
            return GuidanceLevel.CONTEXTUAL

        return GuidanceLevel.NONE

    def _build_explanation(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str:
        return self._message_service.build_explanation(
            issue,
            issue_pattern,
            historical_context,
            history_source,
        )

    def _build_next_step(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str | None:
        return self._message_service.build_next_step(
            issue,
            issue_pattern,
            historical_context,
            history_source,
        )

    def _build_evidence_note(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str | None:
        if not self._should_surface_history(historical_context, history_source):
            return None
        return self._message_service.build_evidence_note(historical_context, history_source)

    def _should_surface_self_explanatory_history(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> bool:
        if not self._message_service.is_local_history_source(history_source):
            return False
        if not self._has_actionable_history(historical_context):
            return False

        assert historical_context is not None
        return self._maintainability_focus(historical_context) in {
            "persistent_debt",
            "accumulating_hotspot",
        }

    def _should_comment_on_maintainability(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> bool:
        if not self._has_actionable_history(historical_context):
            return False

        assert historical_context is not None
        focus = self._maintainability_focus(historical_context)
        if self._message_service.is_local_history_source(history_source):
            return focus in {
                "behavior_sensitive",
                "persistent_debt",
                "later_refactor",
                "accumulating_hotspot",
            }

        return focus in {"behavior_sensitive", "persistent_debt"}

    def _should_surface_history(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> bool:
        if not self._has_actionable_history(historical_context):
            return False

        if self._message_service.is_local_history_source(history_source):
            return True

        assert historical_context is not None
        return self._maintainability_focus(historical_context) in {
            "behavior_sensitive",
            "persistent_debt",
        }

    @staticmethod
    def _needs_duplicate_condition_context(
        historical_context: HistoricalContext | None,
    ) -> bool:
        if not IssueEnricher._has_actionable_history(historical_context):
            return False

        assert historical_context is not None
        if historical_context.dominant_disposition in {"accepted", "persistent"}:
            return True
        if historical_context.dominant_maintenance == "behavior":
            return True

        maintenance_distribution = historical_context.maintenance_distribution
        if len(maintenance_distribution) < 2:
            return False

        top_label, second_label = maintenance_distribution[0][0], maintenance_distribution[1][0]
        if "behavior" not in {top_label, second_label}:
            return False

        return IssueEnricher._is_split_distribution(
            maintenance_distribution,
            sample_size=historical_context.sample_size,
        )

    def _maintainability_focus(self, historical_context: HistoricalContext) -> str:
        return self._message_service.maintainability_focus(historical_context)

    def _build_maintainability_evidence_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str | None:
        return self._message_service.build_evidence_note(historical_context, history_source)

    @staticmethod
    def _is_split_distribution(
        distribution: tuple[tuple[str, int], ...],
        *,
        sample_size: int,
    ) -> bool:
        return DeterministicGuidanceMessageService.is_split_distribution(
            distribution,
            sample_size=sample_size,
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
        if historical_context.dominant_disposition is not None:
            return True
        if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
            return True
        if (
            historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
            and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
        ):
            return True
        if (
            historical_context.dominant_maintenance in {"cleanup", "behavior"}
            and historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        ):
            return True

        return IssueEnricher._is_split_distribution(
            historical_context.maintenance_distribution,
            sample_size=historical_context.sample_size,
        )
