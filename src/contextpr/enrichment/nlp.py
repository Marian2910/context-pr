from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from contextpr.enrichment.history import (
    CombinedHistoricalContext,
    DISPOSITION_LABELS,
    GlobalDatasetHistoryRetriever,
    MAINTENANCE_LABELS,
    HistoricalContext,
    LocalGitHistoryRetriever,
    LocalPullRequestHistoryRetriever,
    LocalReviewCommentHistoryRetriever,
    LocalSonarHistoryRetriever,
)
from contextpr.enrichment.llm import GuidanceVerbalizer
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore

VariantOptions = tuple[str, str, str, str]

MIN_HISTORY_SAMPLE_SIZE = 5
MIN_HISTORY_SHARE = 0.5
MIN_STRONG_HISTORY_MATCHES = 2
HOTSPOT_FILE_MATCHES = 2
HOTSPOT_MODULE_MATCHES = 3
HOTSPOT_MODULE_SHARE = 0.5

PATTERN_BY_RULE = {
    "python:S3923": "duplicate_condition_branches",
    "python:S1172": "unused_function_parameter",
    "python:S1481": "unused_local_variable",
    "python:S1192": "duplicated_literal",
    "python:S1186": "empty_function",
    "python:S1515": "loop_variable_capture",
}

TRIVIAL_PATTERNS = {
    "unused_function_parameter",
    "unused_local_variable",
    "duplicated_literal",
    "empty_function",
}

DETAILED_PATTERNS = {
    "behavior_risk",
    "loop_variable_capture",
}


class GuidanceLevel(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    CONTEXTUAL = "contextual"
    DETAILED = "detailed"


EXPLANATION_OPTIONS: dict[str, VariantOptions] = {
    "loop_variable_capture": (
        "Capture `prefix` when the lambda is created, otherwise later loop iterations can change the value it sees here.",
        "Bind `prefix` at lambda creation time so this closure does not pick up a later loop value.",
        "This lambda should capture the current `prefix` value explicitly, or a later loop iteration may change what it reads.",
        "Make the lambda bind the current `prefix` value instead of relying on the loop variable after it changes.",
    ),
    "correctness": (
        "This may affect runtime behavior, so verify the intended outcome before editing it.",
        "Review this path carefully before changing it because the current behavior may be intentional.",
        "Validate the expected behavior here before rewriting the code around it.",
        "Check what behavior this code is preserving before you refactor it.",
    ),
}

NEXT_STEP_OPTIONS: dict[str, VariantOptions] = {
    "loop_variable_capture": (
        "Pass `prefix` into the lambda as a default argument, or wrap the lambda in a helper that binds the current value.",
        "Add `prefix` as a default argument to the parent lambda so each iteration keeps its own value.",
        "Bind `prefix` explicitly in the lambda signature instead of reading the loop variable after it changes.",
        "Capture the current `prefix` value through a default argument or helper function before the next iteration runs.",
    ),
    "unused_function_parameter": (
        "A good next step is to remove the unused parameter or rename it in a way that makes the intent explicit if the signature must stay as-is.",
        "Consider removing the parameter, or marking it clearly as intentional if the signature cannot change.",
        "A useful next step is to drop the parameter or make its unused role explicit in the signature.",
        "Try removing the unused parameter unless the interface requires it to remain in place.",
    ),
    "unused_local_variable": (
        "A good next step is to remove the variable or replace it with `_` if it is intentional.",
        "Consider deleting the variable, or rename it to `_` if it is intentionally unused.",
        "A useful next step is to remove the unused variable unless it is there only as an intentional placeholder.",
        "Try removing the variable, or make the intent explicit with `_` if it must remain unused.",
    ),
    "duplicated_literal": (
        "A good next step is to extract the repeated literal into a named constant.",
        "Consider replacing the repeated literal with a constant so the intent is clearer in one place.",
        "A useful next step is to centralize the repeated literal behind a constant or shared name.",
        "Try extracting the duplicated literal so the code has a single source of truth for it.",
    ),
    "empty_function": (
        "A good next step is to document why the function is intentionally empty or complete the implementation.",
        "Consider adding a clear explanation for the empty function body, or filling in the missing behavior.",
        "A useful next step is to either justify the empty body in code or complete the implementation.",
        "Try making the empty function intentional and explicit, or implement the missing logic.",
    ),
    "behavior_risk": (
        "Verify the surrounding logic before changing the flagged code path.",
        "Check the surrounding logic to confirm the current behavior is really intended.",
        "Validate the code path against the expected behavior before changing it.",
        "Review the flagged logic path against the expected behavior before editing it.",
    ),
}


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
        guidance_verbalizer: GuidanceVerbalizer | None = None,
        *,
        enable_local_history: bool = False,
        enable_local_git_history: bool = True,
        history_store: HistoryStore | None = None,
        repository_key: str | None = None,
    ) -> None:
        self._global_history_retriever = GlobalDatasetHistoryRetriever(dataset_path)
        self._guidance_verbalizer = guidance_verbalizer
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

        if self._enable_local_history:
            local_sonar = self._actionable_or_none(
                self._local_history_retriever.find_context(issue)
                if self._local_history_retriever is not None
                else None
            )
            local_git = self._actionable_or_none(
                self._local_git_history_retriever.find_context(issue)
                if self._local_git_history_retriever is not None
                else None
            )
            local_prs = self._actionable_or_none(
                self._local_pr_history_retriever.find_context(issue)
                if self._local_pr_history_retriever is not None
                else None
            )
            local_review_comments = self._actionable_or_none(
                self._local_review_comment_history_retriever.find_context(issue)
                if self._local_review_comment_history_retriever is not None
                else None
            )
            historical_context = CombinedHistoricalContext(
                local_sonar=local_sonar,
                local_git=local_git,
                local_prs=local_prs,
                local_review_comments=local_review_comments,
                global_dataset=None,
            )
            if historical_context.preferred_source_name() is None:
                historical_context = CombinedHistoricalContext(
                    local_sonar=local_sonar,
                    local_git=local_git,
                    local_prs=local_prs,
                    local_review_comments=local_review_comments,
                    global_dataset=self._actionable_or_none(
                        self._global_history_retriever.find_context(issue)
                    ),
                )
        else:
            historical_context = CombinedHistoricalContext(
                global_dataset=self._actionable_or_none(
                    self._global_history_retriever.find_context(issue)
                )
            )
        active_history = self._active_history(historical_context)
        active_source = self._active_source(historical_context)
        guidance = self._build_guidance(issue, active_history, active_source)
        if guidance is None:
            return None

        if self._guidance_verbalizer is not None and guidance.level is not GuidanceLevel.MINIMAL:
            guidance = self._guidance_verbalizer.rewrite(issue, guidance, historical_context)

        return IssueEnrichment(
            guidance=guidance,
            historical_context=historical_context,
        )

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

        explanation = self._build_explanation(issue, historical_context, history_source)
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
            return "duplicate_condition_branches"
        if "unused function parameter" in message:
            return "unused_function_parameter"
        if "unused local variable" in message:
            return "unused_local_variable"
        if "duplicating this literal" in message:
            return "duplicated_literal"
        if "function is empty" in message or issue.rule == "python:S1186":
            return "empty_function"
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

        if issue_pattern == "duplicate_condition_branches":
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
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str:
        issue_pattern = self._issue_pattern(issue)
        if issue_pattern == "loop_variable_capture":
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS[issue_pattern],
            )

        if issue.issue_type == "BUG":
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS["correctness"],
            )

        direct_explanation = self._issue_specific_maintainability_explanation(
            issue,
            issue_pattern,
        )
        if direct_explanation is not None:
            return direct_explanation

        assert historical_context is not None
        return self._build_maintainability_explanation(historical_context, history_source)

    def _build_next_step(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str:
        if issue_pattern == "loop_variable_capture":
            return self._pick_required_option(
                issue_pattern,
                "next_step",
                NEXT_STEP_OPTIONS[issue_pattern],
            )

        if issue.issue_type == "BUG":
            return self._pick_required_option(
                "behavior_risk",
                "next_step",
                NEXT_STEP_OPTIONS["behavior_risk"],
            )

        if issue.issue_type == "CODE_SMELL":
            return None

        assert historical_context is not None
        return self._build_maintainability_next_step(historical_context, history_source)

    def _issue_specific_maintainability_explanation(
        self,
        issue: SonarIssue,
        issue_pattern: str,
    ) -> str | None:
        if issue_pattern == "duplicate_condition_branches":
            return (
                "These branches currently do the same thing, so collapse them only if "
                "the separation is not preserving a behavior difference."
            )

        if issue.issue_type != "CODE_SMELL":
            return None

        return self._normalize_issue_message(issue.message)

    @staticmethod
    def _normalize_issue_message(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return message
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized

    def _build_evidence_note(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str | None:
        if not self._should_surface_history(historical_context, history_source):
            return None

        assert historical_context is not None
        return self._build_maintainability_evidence_note(historical_context, history_source)

    @staticmethod
    def _is_local_history_source(history_source: str | None) -> bool:
        return history_source in {
            "local_sonar",
            "local_git",
            "local_prs",
            "local_review_comments",
        }

    def _should_surface_self_explanatory_history(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> bool:
        if not self._is_local_history_source(history_source):
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
        if self._is_local_history_source(history_source):
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

        if self._is_local_history_source(history_source):
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

        top_label, top_count = maintenance_distribution[0]
        second_label, second_count = maintenance_distribution[1]
        if "behavior" not in {top_label, second_label}:
            return False

        sample_size = historical_context.sample_size
        if sample_size <= 0:
            return False

        top_share = top_count / sample_size
        second_share = second_count / sample_size
        return second_share >= 0.3 and top_share - second_share <= 0.2

    def _build_maintainability_explanation(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        location_subject = self._location_subject(historical_context, history_source)
        focus = self._maintainability_focus(historical_context)
        if focus == "behavior_sensitive":
            return (
                f"Similar cleanup in {location_subject} often touched behavior-sensitive paths, "
                "so check whether this structure is carrying intent before simplifying it."
            )
        if focus == "persistent_debt":
            return (
                f"Similar smells in {location_subject} often stayed around across later changes, "
                "so this is worth deciding on while the code is already open."
            )
        if focus == "later_refactor":
            return (
                f"Similar smells in {location_subject} were often handled later during cleanup work "
                "instead of immediately."
            )
        if focus == "accumulating_hotspot":
            return (
                f"Similar smells have shown up more than once in {location_subject}, "
                "so this is probably not a one-off cleanup."
            )
        return (
            f"Similar cases in {location_subject} have needed follow-up cleanup more than once."
        )

    def _build_maintainability_next_step(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        _ = history_source
        focus = self._maintainability_focus(historical_context)
        if focus == "behavior_sensitive":
            return (
                "If you simplify it, verify that the current structure is not preserving "
                "a behavior difference."
            )
        if focus == "persistent_debt":
            return (
                "If you are already touching this code, either fix it now or leave a clear note "
                "about why it is staying."
            )
        if focus == "later_refactor":
            return (
                "If the cleanup is straightforward here, fixing it now may avoid another cleanup pass later."
            )
        if focus == "accumulating_hotspot":
            return (
                "Use this touchpoint to simplify or narrow the smell while the code is already open."
            )
        return (
            "Consider addressing it in this change or leaving an explicit note if it is staying for now."
        )

    def _build_maintainability_evidence_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str | None:
        evidence_subject = self._evidence_subject(historical_context, history_source)
        evidence_pattern = self._evidence_pattern_clause(historical_context)
        decision_support = self._decision_support_clause(historical_context, history_source)
        if evidence_subject and evidence_pattern and decision_support:
            return f"{evidence_subject} {evidence_pattern}, so {decision_support}."
        if evidence_subject and evidence_pattern:
            return f"{evidence_subject} {evidence_pattern}."
        if decision_support:
            return decision_support[:1].upper() + decision_support[1:] + "."
        return None

    @staticmethod
    def _evidence_subject(
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str | None:
        if history_source in {
            "local_sonar",
            "local_git",
            "local_prs",
            "local_review_comments",
        }:
            if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
                return "Similar local cases in this file"
            if (
                historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
                and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
            ):
                return "Similar local cases in this module area"
            return None
        if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
            return "Historically similar matches for the same file path"
        if (
            historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
            and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
        ):
            return "Historically similar matches for similar module paths"
        return None

    @staticmethod
    def _evidence_pattern_clause(historical_context: HistoricalContext) -> str | None:
        disposition_distribution = historical_context.disposition_distribution
        if disposition_distribution:
            if IssueEnricher._is_split_distribution(
                disposition_distribution,
                sample_size=sum(count for _, count in disposition_distribution),
            ):
                first, second = disposition_distribution[:2]
                return (
                    f"were split between {DISPOSITION_LABELS[first[0]]} "
                    f"and {DISPOSITION_LABELS[second[0]]}"
                )
            if (
                historical_context.dominant_disposition is not None
                and historical_context.dominant_disposition_share >= MIN_HISTORY_SHARE
            ):
                if historical_context.dominant_disposition == "persistent":
                    return "often stayed unresolved across later changes"
                if historical_context.dominant_disposition == "accepted":
                    return "were often kept as accepted debt"
                return "were usually fixed"

        maintenance_distribution = historical_context.maintenance_distribution
        if not maintenance_distribution:
            return None

        if IssueEnricher._is_split_distribution(
            maintenance_distribution,
            sample_size=historical_context.sample_size,
        ):
            first, second = maintenance_distribution[:2]
            return (
                f"were split between {MAINTENANCE_LABELS[first[0]]} "
                f"and {MAINTENANCE_LABELS[second[0]]}"
            )

        if (
            historical_context.dominant_maintenance == "cleanup"
            and historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        ):
            return "were usually fixed as small clean-ups"
        if (
            historical_context.dominant_maintenance == "behavior"
            and historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        ):
            return "more often needed behavior-aware follow-up than quick cleanup"
        return None

    def _decision_support_clause(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str | None:
        focus = self._maintainability_focus(historical_context)
        if focus == "behavior_sensitive":
            return "inspect the surrounding logic before simplifying it"
        if focus == "persistent_debt":
            if self._is_local_history_source(history_source):
                return "decide explicitly whether to fix it now or leave it for follow-up"
            return "it is worth deciding explicitly whether this should be fixed now"
        if focus in {"later_refactor", "accumulating_hotspot"}:
            if self._is_local_history_source(history_source):
                return "this is probably worth resolving in this PR if the cleanup is small"
            return None
        return None

    @staticmethod
    def _location_subject(
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        if history_source in {
            "local_sonar",
            "local_git",
            "local_prs",
            "local_review_comments",
        }:
            if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
                return "this file"
            if (
                historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
                and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
            ):
                return "this module area"
            return "this repository"
        if historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES:
            return "matching file paths"
        if (
            historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
            and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
        ):
            return "similar module paths"
        return "similar code areas"

    @staticmethod
    def _maintainability_focus(historical_context: HistoricalContext) -> str:
        if (
            historical_context.dominant_maintenance == "behavior"
            and historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        ):
            return "behavior_sensitive"
        if (
            historical_context.dominant_disposition in {"persistent", "accepted"}
            and historical_context.dominant_disposition_share >= MIN_HISTORY_SHARE
        ):
            return "persistent_debt"
        if (
            historical_context.dominant_maintenance == "cleanup"
            and historical_context.dominant_maintenance_share >= MIN_HISTORY_SHARE
        ):
            return "later_refactor"
        if (
            historical_context.same_exact_path_matches >= HOTSPOT_FILE_MATCHES
            or (
                historical_context.same_path_family_matches >= HOTSPOT_MODULE_MATCHES
                and historical_context.same_path_family_share >= HOTSPOT_MODULE_SHARE
            )
        ):
            return "accumulating_hotspot"
        return "recurring_maintenance"

    @staticmethod
    def _is_split_distribution(
        distribution: tuple[tuple[str, int], ...],
        *,
        sample_size: int,
    ) -> bool:
        if len(distribution) < 2 or sample_size <= 0:
            return False

        top_count = distribution[0][1]
        second_count = distribution[1][1]
        top_share = top_count / sample_size
        second_share = second_count / sample_size
        return second_share >= 0.3 and top_share - second_share <= 0.2

    @staticmethod
    def _has_grounded_history(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None:
            return False

        if historical_context.sample_size < MIN_HISTORY_SAMPLE_SIZE:
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

    @staticmethod
    def _pick_required_option(
        subject: SonarIssue | str,
        salt: str,
        options: VariantOptions,
    ) -> str:
        if isinstance(subject, SonarIssue):
            key = "|".join(
                (
                    subject.rule,
                    subject.message,
                    subject.location.path,
                    salt,
                )
            )
        else:
            key = f"{subject}|{salt}"

        index = sum(ord(char) for char in key) % len(options)
        return options[index]
