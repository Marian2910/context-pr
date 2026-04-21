from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from contextpr.enrichment.history import HistoricalContext, IssueHistoryRetriever
from contextpr.enrichment.intent import IntentPrediction
from contextpr.models import SonarIssue

VariantOptions = tuple[str, str, str, str]

MIN_HISTORY_SAMPLE_SIZE = 5
MIN_HISTORY_LABEL_SHARE = 0.5
MIN_STRONG_HISTORY_MATCHES = 2

PATTERN_BY_RULE = {
    "python:S3923": "duplicate_condition_branches",
    "python:S1172": "unused_function_parameter",
    "python:S1481": "unused_local_variable",
    "python:S1192": "duplicated_literal",
    "python:S1186": "empty_function",
}

TRIVIAL_PATTERNS = {
    "unused_function_parameter",
    "unused_local_variable",
    "duplicated_literal",
    "empty_function",
}

DETAILED_PATTERNS = {
    "duplicate_condition_branches",
    "behavior_risk",
}

BUCKET_LABELS = {
    "cleanup": "routine cleanup",
    "behavior": "behavior-oriented fixes",
    "supporting": "supporting updates",
}


class GuidanceLevel(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    CONTEXTUAL = "contextual"
    DETAILED = "detailed"


SUMMARY_BY_PATTERN: dict[str, str] = {
    "duplicate_condition_branches": (
        "Sonar flagged this because all branches of the condition appear to do "
        "the same thing."
    ),
    "unused_function_parameter": (
        "Sonar flagged this because a function parameter appears to be unused."
    ),
    "unused_local_variable": (
        "Sonar flagged this because a local variable appears to be unused."
    ),
    "duplicated_literal": (
        "Sonar flagged this because the same literal is repeated in multiple "
        "places."
    ),
    "empty_function": "Sonar flagged this because a function body appears to be empty.",
    "behavior_risk": "Sonar flagged this because the code may not behave as intended.",
    "cleanup_candidate": (
        "Sonar flagged this because the code could be simplified or clarified."
    ),
    "general_review": "Sonar flagged this code for review.",
}

EXPLANATION_OPTIONS: dict[str, VariantOptions] = {
    "behavior": (
        "This looks more like a behavior issue than a simple cleanup.",
        "This warning suggests the code may need a logic change, not just a tidy-up.",
        "This reads more like a correctness concern than a stylistic cleanup.",
        (
            "This is probably worth treating as logic-related work rather than "
            "routine cleanup."
        ),
    ),
    "supporting": (
        (
            "This looks like a small follow-up around the flagged code rather "
            "than a large logic change."
        ),
        (
            "This seems more like supporting work around the flagged code than "
            "a direct behavior change."
        ),
        (
            "This warning usually leads to a light follow-up rather than a "
            "deeper logic rewrite."
        ),
        (
            "This looks like a nearby follow-up task more than a core behavior "
            "fix."
        ),
    ),
    "correctness": (
        "This is worth checking carefully because it may affect behavior.",
        "This deserves a closer look because it could change how the code behaves.",
        (
            "This warning is worth reviewing carefully in case it affects "
            "runtime behavior."
        ),
        (
            "This is the kind of issue that is worth validating against the "
            "intended behavior."
        ),
    ),
    "cleanup": (
        "This looks like a cleanup issue rather than a functional change.",
        "This seems more like code cleanup than a behavior fix.",
        "This warning points more toward simplification than a change in behavior.",
        "This looks like something to clean up rather than a functional defect.",
    ),
}

NEXT_STEP_OPTIONS: dict[str, VariantOptions] = {
    "duplicate_condition_branches": (
        (
            "A good next step is to simplify the condition or remove duplicated "
            "branches if they are truly equivalent."
        ),
        (
            "Consider collapsing the conditional if all branches are effectively "
            "doing the same work."
        ),
        (
            "Try simplifying the control flow so each branch has a distinct "
            "outcome, or remove the condition entirely."
        ),
        (
            "A useful next step is to rewrite or remove the conditional so it "
            "no longer repeats the same behavior."
        ),
    ),
    "unused_function_parameter": (
        (
            "A good next step is to remove the unused parameter or rename it in "
            "a way that makes the intent explicit if the signature must stay as-is."
        ),
        (
            "Consider removing the parameter, or marking it clearly as "
            "intentional if the signature cannot change."
        ),
        (
            "A useful next step is to drop the parameter or make its unused role "
            "explicit in the signature."
        ),
        (
            "Try removing the unused parameter unless the interface requires it "
            "to remain in place."
        ),
    ),
    "unused_local_variable": (
        (
            "A good next step is to remove the variable or replace it with `_` "
            "if it is intentional."
        ),
        (
            "Consider deleting the variable, or rename it to `_` if it is "
            "intentionally unused."
        ),
        (
            "A useful next step is to remove the unused variable unless it is "
            "there only as an intentional placeholder."
        ),
        (
            "Try removing the variable, or make the intent explicit with `_` if "
            "it must remain unused."
        ),
    ),
    "duplicated_literal": (
        "A good next step is to extract the repeated literal into a named constant.",
        (
            "Consider replacing the repeated literal with a constant so the "
            "intent is clearer in one place."
        ),
        (
            "A useful next step is to centralize the repeated literal behind a "
            "constant or shared name."
        ),
        (
            "Try extracting the duplicated literal so the code has a single "
            "source of truth for it."
        ),
    ),
    "empty_function": (
        (
            "A good next step is to document why the function is intentionally "
            "empty or complete the implementation."
        ),
        (
            "Consider adding a clear explanation for the empty function body, or "
            "filling in the missing behavior."
        ),
        (
            "A useful next step is to either justify the empty body in code or "
            "complete the implementation."
        ),
        (
            "Try making the empty function intentional and explicit, or "
            "implement the missing logic."
        ),
    ),
    "behavior_risk": (
        "A good next step is to verify the logic around the flagged code path.",
        (
            "Consider checking the surrounding logic to confirm the current "
            "behavior is really intended."
        ),
        (
            "A useful next step is to validate the code path and confirm it "
            "behaves as expected."
        ),
        (
            "Try reviewing the flagged logic path against the expected behavior "
            "before changing it."
        ),
    ),
    "general_review": (
        "A good next step is to simplify or clarify the flagged code where possible.",
        (
            "Consider simplifying the flagged code so the intent is easier to "
            "read directly."
        ),
        "A useful next step is to make the flagged code clearer and easier to follow.",
        (
            "Try simplifying the flagged code so the intent is more obvious at a "
            "glance."
        ),
    ),
}

@dataclass(frozen=True, slots=True)
class DeveloperGuidance:
    level: GuidanceLevel
    summary: str | None = None
    explanation: str | None = None
    next_step: str | None = None
    evidence_note: str | None = None


@dataclass(frozen=True, slots=True)
class IssueEnrichment:
    guidance: DeveloperGuidance
    intent_prediction: IntentPrediction | None
    historical_context: HistoricalContext | None


class IssueEnricher:

    def __init__(self, model_path: Path, dataset_path: Path) -> None:
        self._model_path = model_path
        self._history_retriever = IssueHistoryRetriever(dataset_path)

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        historical_context = self._history_retriever.find_context(issue)
        guidance = self._build_guidance(issue, historical_context)
        if guidance is None:
            return None

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

        evidence_note = self._build_evidence_note(issue, historical_context)
        if guidance_level is GuidanceLevel.MINIMAL:
            return DeveloperGuidance(level=guidance_level, evidence_note=evidence_note)

        summary = (
            self._build_summary(issue_pattern)
            if guidance_level is GuidanceLevel.DETAILED
            else None
        )
        explanation = self._build_explanation(issue, historical_context)
        next_step = (
            self._build_next_step(issue_pattern)
            if guidance_level is GuidanceLevel.DETAILED
            else None
        )

        return DeveloperGuidance(
            level=guidance_level,
            summary=summary,
            explanation=explanation,
            next_step=next_step,
            evidence_note=evidence_note,
        )

    def _build_summary(self, issue_pattern: str) -> str:
        return SUMMARY_BY_PATTERN.get(issue_pattern, SUMMARY_BY_PATTERN["general_review"])

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
        issue_kind = self._issue_kind(issue)
        change_kind = self._change_kind(historical_context, issue_kind)
        option_key = change_kind if change_kind != "cleanup" else issue_kind
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
        issue: SonarIssue,
        historical_context: HistoricalContext | None,
    ) -> str | None:
        if not self._has_grounded_history(historical_context):
            return None

        change_kind = self._change_kind(
            historical_context,
            self._issue_kind(issue),
        )
        return self._history_note(historical_context, change_kind)

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
        if (
            "unused" in message
            or "duplicating this literal" in message
        ):
            return "cleanup"
        if issue.tags and any(tag in {"design", "unused", "suspicious"} for tag in issue.tags):
            return "cleanup"
        return "general"

    def _change_kind(
        self,
        historical_context: HistoricalContext | None,
        issue_kind: str,
    ) -> str:
        if issue_kind == "correctness":
            return "behavior"
        if issue_kind == "cleanup":
            return "cleanup"

        label_scores = self._label_scores(historical_context)
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
        historical_context: HistoricalContext | None,
    ) -> dict[str, float]:
        scores = {"cleanup": 0.0, "behavior": 0.0, "supporting": 0.0}
        if not IssueEnricher._has_grounded_history(historical_context):
            return scores

        assert historical_context is not None
        for label, count in historical_context.label_distribution:
            scores[IssueEnricher._bucket_for_label(label)] += (
                count / historical_context.sample_size
            )
        return scores

    @staticmethod
    def _bucket_counts(historical_context: HistoricalContext) -> Counter[str]:
        counts: Counter[str] = Counter()
        for label, count in historical_context.label_distribution:
            counts[IssueEnricher._bucket_for_label(label)] += count
        return counts

    @staticmethod
    def _history_note(
        historical_context: HistoricalContext | None,
        change_kind: str,
    ) -> str | None:
        if historical_context is None:
            return None

        counts = IssueEnricher._bucket_counts(historical_context)
        if not counts:
            return None

        ranked = counts.most_common()
        top_bucket, top_count = ranked[0]
        top_share = top_count / historical_context.sample_size
        if len(ranked) > 1:
            second_bucket, second_count = ranked[1]
            second_share = second_count / historical_context.sample_size
            if second_share >= 0.3 and top_share - second_share <= 0.2:
                return (
                    "Historical note: similar cases were split between "
                    f"{BUCKET_LABELS[top_bucket]} and {BUCKET_LABELS[second_bucket]}."
                )

        phrase = IssueEnricher._history_strength_phrase(historical_context)
        bucket_label = BUCKET_LABELS.get(change_kind, BUCKET_LABELS[top_bucket])
        return f"Historical note: {phrase} {bucket_label}."

    @staticmethod
    def _history_strength_phrase(historical_context: HistoricalContext) -> str:
        if (
            historical_context.sample_size >= 15
            and historical_context.same_rule_matches >= 5
            and historical_context.strongest_label_share >= 0.75
        ):
            return "similar cases were usually handled as"

        if (
            historical_context.sample_size >= 8
            and historical_context.same_rule_matches >= 3
            and historical_context.strongest_label_share >= 0.65
        ):
            return "similar cases were often handled as"

        return "in a small set of similar cases, developers leaned toward"

    @staticmethod
    def _has_grounded_history(historical_context: HistoricalContext | None) -> bool:
        if historical_context is None:
            return False

        if historical_context.sample_size < MIN_HISTORY_SAMPLE_SIZE:
            return False

        has_rule_support = historical_context.same_rule_matches > 0
        has_label_consensus = historical_context.strongest_label_share >= MIN_HISTORY_LABEL_SHARE
        has_strong_matches = historical_context.strong_match_count >= MIN_STRONG_HISTORY_MATCHES
        return has_rule_support and has_label_consensus and has_strong_matches

    @staticmethod
    def _bucket_for_label(label: str) -> str:
        normalized = label.strip().lower()
        if normalized in {"fix", "feat", "perf"}:
            return "behavior"
        if normalized in {"docs", "test", "build", "ci"}:
            return "supporting"
        return "cleanup"

    @staticmethod
    def _variant_index(issue: SonarIssue, scope: str) -> int:
        token = f"{scope}:{issue.rule}:{issue.message}"
        return sum(ord(char) for char in token) % 4

    @staticmethod
    def _variant_index_for_token(token: str, scope: str) -> int:
        scoped_token = f"{scope}:{token}"
        return sum(ord(char) for char in scoped_token) % 4

    def _pick_option(
        self,
        issue_or_token: SonarIssue | str,
        scope: str,
        options: VariantOptions | None,
    ) -> str | None:
        if options is None:
            return None

        if isinstance(issue_or_token, SonarIssue):
            variant = self._variant_index(issue_or_token, scope)
        else:
            variant = self._variant_index_for_token(issue_or_token, scope)

        return options[variant]

    def _pick_required_option(
        self,
        issue_or_token: SonarIssue | str,
        scope: str,
        options: VariantOptions,
    ) -> str:
        selected = self._pick_option(issue_or_token, scope, options)
        return selected or options[0]
