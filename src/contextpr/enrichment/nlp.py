from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from contextpr.enrichment.history import (
    DISPOSITION_LABELS,
    MAINTENANCE_LABELS,
    HistoricalContext,
    IssueHistoryRetriever,
)
from contextpr.enrichment.intent import IntentPrediction
from contextpr.enrichment.llm import GuidanceVerbalizer
from contextpr.models import SonarIssue

VariantOptions = tuple[str, str, str, str]

MIN_HISTORY_SAMPLE_SIZE = 5
MIN_HISTORY_SHARE = 0.5
MIN_STRONG_HISTORY_MATCHES = 2

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
    "behavior": (
        "Treat this as behavior-sensitive: changing it may alter how the code runs.",
        "This change is worth reviewing carefully because it can affect runtime behavior.",
        "Handle this as a logic concern, not as a mechanical rewrite.",
        "Check the intended behavior before simplifying this code path.",
    ),
    "correctness": (
        "This may affect runtime behavior, so verify the intended outcome before editing it.",
        "Review this path carefully before changing it because the current behavior may be intentional.",
        "Validate the expected behavior here before rewriting the code around it.",
        "Check what behavior this code is preserving before you refactor it.",
    ),
    "cleanup": (
        "This is probably safe to simplify if the current structure is not intentional.",
        "This looks like code that can be simplified without changing the intended behavior.",
        "The main value here is to make the code easier to read and maintain.",
        "This is a good candidate for a small refactor if there is no hidden intent in the current structure.",
    ),
}

NEXT_STEP_OPTIONS: dict[str, VariantOptions] = {
    "duplicate_condition_branches": (
        "Before simplifying the conditional, verify that the repeated branches are not intentionally preserving behavior or readability.",
        "Check whether the duplicated branches are intentional before collapsing the conditional.",
        "Verify that the identical branches are not documenting an intentional distinction before removing the duplication.",
        "Review whether the repeated branches are deliberately kept separate before simplifying the control flow.",
    ),
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
    "general_review": (
        "A good next step is to simplify or clarify the flagged code where possible.",
        "Consider simplifying the flagged code so the intent is easier to read directly.",
        "A useful next step is to make the flagged code clearer and easier to follow.",
        "Try simplifying the flagged code so the intent is more obvious at a glance.",
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
    intent_prediction: IntentPrediction | None
    historical_context: HistoricalContext | None


class IssueEnricher:
    def __init__(
        self,
        model_path: Path,
        dataset_path: Path,
        guidance_verbalizer: GuidanceVerbalizer | None = None,
    ) -> None:
        self._model_path = model_path
        self._history_retriever = IssueHistoryRetriever(dataset_path)
        self._guidance_verbalizer = guidance_verbalizer

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        historical_context = self._history_retriever.find_context(issue)
        guidance = self._build_guidance(issue, historical_context)
        if guidance is None:
            return None

        if self._guidance_verbalizer is not None and guidance.level is not GuidanceLevel.MINIMAL:
            guidance = self._guidance_verbalizer.rewrite(issue, guidance, historical_context)

        return IssueEnrichment(
            guidance=guidance,
            intent_prediction=None,
            historical_context=historical_context,
        )

    def _build_guidance(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
    ) -> DeveloperGuidance | None:
        issue_pattern = self._issue_pattern(issue)
        guidance_level = self._guidance_level(issue, issue_pattern, historical_context)
        if guidance_level is GuidanceLevel.NONE:
            return None

        evidence_note = self._build_evidence_note(historical_context)
        if guidance_level is GuidanceLevel.MINIMAL:
            return DeveloperGuidance(level=guidance_level, evidence_note=evidence_note)

        explanation = self._build_explanation(issue, historical_context)
        next_step = (
            self._build_next_step(issue_pattern)
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
    ) -> GuidanceLevel:
        has_grounded_history = self._has_grounded_history(historical_context)
        if issue_pattern in TRIVIAL_PATTERNS:
            return GuidanceLevel.MINIMAL if has_grounded_history else GuidanceLevel.NONE

        if issue_pattern == "duplicate_condition_branches":
            return (
                GuidanceLevel.DETAILED
                if self._needs_duplicate_condition_context(historical_context)
                else GuidanceLevel.NONE
            )

        if issue_pattern in DETAILED_PATTERNS or issue.issue_type == "BUG":
            return GuidanceLevel.DETAILED

        if has_grounded_history:
            return GuidanceLevel.CONTEXTUAL

        return GuidanceLevel.NONE

    def _build_explanation(
        self,
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
    ) -> str:
        issue_pattern = self._issue_pattern(issue)
        if issue_pattern in EXPLANATION_OPTIONS:
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS[issue_pattern],
            )

        issue_kind = self._issue_kind(issue)
        utility_kind = self._utility_kind(historical_context, issue_kind)
        option_key = utility_kind if utility_kind != "cleanup" else issue_kind
        if option_key not in EXPLANATION_OPTIONS:
            option_key = "cleanup"
        return self._pick_required_option(
            issue,
            "explanation",
            EXPLANATION_OPTIONS[option_key],
        )

    def _build_next_step(self, issue_pattern: str) -> str:
        option_key = issue_pattern if issue_pattern != "cleanup_candidate" else "general_review"
        return self._pick_required_option(
            option_key,
            "next_step",
            NEXT_STEP_OPTIONS[option_key],
        )

    def _build_evidence_note(
        self,
        historical_context: HistoricalContext | None,
    ) -> str | None:
        if not self._has_grounded_history(historical_context):
            return None

        assert historical_context is not None
        if historical_context.dominant_disposition is not None:
            return self._history_note_from_disposition(historical_context)
        return self._history_note_from_maintenance(historical_context)

    @staticmethod
    def _issue_kind(issue: SonarIssue) -> str:
        pattern = PATTERN_BY_RULE.get(issue.rule)
        if pattern in TRIVIAL_PATTERNS:
            return "cleanup"
        if pattern == "duplicate_condition_branches":
            return "general"

        message = issue.message.lower()
        if issue.issue_type == "BUG":
            return "correctness"
        if "unused" in message or "duplicating this literal" in message:
            return "cleanup"
        if issue.tags and any(tag in {"design", "unused", "suspicious"} for tag in issue.tags):
            return "cleanup"
        return "general"

    def _utility_kind(
        self,
        historical_context: HistoricalContext | None,
        issue_kind: str,
    ) -> str:
        if issue_kind == "correctness":
            return "behavior"
        if issue_kind == "cleanup":
            return "cleanup"
        if historical_context is None or historical_context.dominant_maintenance is None:
            return "cleanup"
        if historical_context.dominant_maintenance == "supporting":
            return "cleanup"
        return historical_context.dominant_maintenance

    @staticmethod
    def _needs_duplicate_condition_context(
        historical_context: HistoricalContext | None,
    ) -> bool:
        if not IssueEnricher._has_grounded_history(historical_context):
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

    @staticmethod
    def _history_note_from_disposition(historical_context: HistoricalContext) -> str | None:
        distribution = historical_context.disposition_distribution
        if not distribution:
            return None

        if IssueEnricher._is_split_distribution(
            distribution,
            sample_size=sum(count for _, count in distribution),
        ):
            first, second = distribution[:2]
            return (
                "Similar cases here were split between "
                f"{DISPOSITION_LABELS[first[0]]} and {DISPOSITION_LABELS[second[0]]}."
            )

        strength_phrase = IssueEnricher._history_strength_phrase(
            sample_size=historical_context.sample_size,
            same_rule_matches=historical_context.same_rule_matches,
            dominant_share=historical_context.dominant_disposition_share,
        )
        label = DISPOSITION_LABELS[historical_context.dominant_disposition or "resolved"]
        return f"{strength_phrase.capitalize()} {label}."

    @staticmethod
    def _history_note_from_maintenance(historical_context: HistoricalContext) -> str | None:
        distribution = historical_context.maintenance_distribution
        if not distribution:
            return None

        if (
            historical_context.dominant_maintenance == "supporting"
            and historical_context.dominant_disposition is None
        ):
            return None

        if IssueEnricher._is_split_distribution(
            distribution,
            sample_size=historical_context.sample_size,
        ):
            first, second = distribution[:2]
            return (
                "Similar cases here were split between "
                f"{MAINTENANCE_LABELS[first[0]]} and {MAINTENANCE_LABELS[second[0]]}."
            )

        strength_phrase = IssueEnricher._history_strength_phrase(
            sample_size=historical_context.sample_size,
            same_rule_matches=historical_context.same_rule_matches,
            dominant_share=historical_context.dominant_maintenance_share,
        )
        label = MAINTENANCE_LABELS[
            historical_context.dominant_maintenance or distribution[0][0]
        ]
        return f"{strength_phrase.capitalize()} {label}."

    @staticmethod
    def _history_strength_phrase(
        *,
        sample_size: int,
        same_rule_matches: int,
        dominant_share: float,
    ) -> str:
        if sample_size >= 15 and same_rule_matches >= 5 and dominant_share >= 0.75:
            return "similar cases here were usually"
        if sample_size >= 8 and same_rule_matches >= 3 and dominant_share >= 0.65:
            return "similar cases here were often"
        return "in a small set of similar cases, developers leaned toward"

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
