from __future__ import annotations

from contextpr.enrichment.history import HistoricalContext
from contextpr.models import SonarIssue

VariantOptions = tuple[str, str, str, str]

LOCAL_HISTORY_SOURCES = {
    "local_sonar",
    "local_git",
    "local_prs",
    "local_review_comments",
}

EXPLANATION_OPTIONS: dict[str, VariantOptions] = {
    "inspect_before_changing": (
        "This is worth checking before simplifying.",
        "Check this before simplifying it.",
        "This needs a quick check before you simplify it.",
        "Before changing this, verify the current code path.",
    ),
}

NEXT_STEP_OPTIONS: dict[str, VariantOptions] = {
    "inspect_before_changing": (
        "Verify the current code path before changing it.",
        "Check the affected path before making this simplification.",
        "Review the surrounding code before changing it.",
        "Verify the flagged code path before rewriting it.",
    ),
}

class DeterministicGuidanceMessageService:
    def build_explanation(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        context_signals: object | None = None,
        historical_context: HistoricalContext | None = None,
        history_source: str | None = None,
    ) -> str:
        _ = context_signals, historical_context, history_source
        if issue_pattern in {
            "inspect_before_changing",
            "behavior_sensitive_cleanup",
            "behavior_risk",
        }:
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS["inspect_before_changing"],
            )
        return self._normalize_issue_message(issue.message)

    def build_next_step(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        context_signals: object | None = None,
        historical_context: HistoricalContext | None = None,
        history_source: str | None = None,
    ) -> str | None:
        if issue_pattern in {
            "inspect_before_changing",
            "behavior_sensitive_cleanup",
            "behavior_risk",
        }:
            return self._pick_required_option(
                issue,
                "next_step",
                NEXT_STEP_OPTIONS["inspect_before_changing"],
            )
        if issue_pattern == "general_review" and historical_context is not None:
            _ = context_signals, history_source
            return (
                "If the fix is local to the current change, address it in this PR; "
                "otherwise make the follow-up decision explicit."
            )
        return None

    def build_evidence_note(
        self,
        issue: SonarIssue | HistoricalContext | None,
        issue_pattern: str | None = None,
        context_signals: object | None = None,
        historical_context: HistoricalContext | None = None,
        history_source: str | None = None,
    ) -> str | None:
        if isinstance(issue, HistoricalContext) or issue is None:
            historical_context = issue
            issue = None
            history_source = issue_pattern
            issue_pattern = None

        if historical_context is None:
            return None

        if issue is None or issue_pattern is None:
            return self._compatibility_evidence_note(historical_context, history_source)

        if issue_pattern == "worth_fixing_now":
            return self._fix_now_note(issue, context_signals, historical_context, history_source)
        if issue_pattern == "decide_before_deferring":
            return self._defer_decision_note(historical_context, history_source)
        if issue_pattern == "recurs_here":
            return self._recurrence_note(historical_context, history_source)
        return None

    @staticmethod
    def is_local_history_source(history_source: str | None) -> bool:
        return history_source in LOCAL_HISTORY_SOURCES

    @staticmethod
    def is_split_distribution(
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

    def maintainability_focus(self, historical_context: HistoricalContext) -> str:
        if historical_context.dominant_maintenance == "behavior":
            return "behavior_sensitive"
        if historical_context.dominant_disposition in {"persistent", "accepted"}:
            return "persistent_debt"
        if historical_context.dominant_maintenance == "cleanup":
            return "later_refactor"
        if historical_context.same_exact_path_matches >= 2:
            return "accumulating_hotspot"
        if historical_context.same_path_family_matches >= 3:
            return "accumulating_hotspot"
        return "recurring_maintenance"

    def _compatibility_evidence_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str | None:
        focus = self.maintainability_focus(historical_context)
        if focus == "persistent_debt":
            return self._defer_decision_note(historical_context, history_source)
        if focus == "later_refactor":
            return (
                f"{self._history_subject(historical_context, history_source)}, "
                "similar cases of this rule were often fixed as small cleanup work.\n\n"
                "Since this issue is new in the PR, it is worth fixing here."
            )
        if focus == "accumulating_hotspot":
            return self._recurrence_note(historical_context, history_source)
        if focus == "behavior_sensitive":
            return (
                f"{self._history_subject(historical_context, history_source)}, "
                "similar cases for this rule were split between cleanup and behavior-preserving edits.\n\n"
                "Check the current code path before simplifying this."
            )
        return None

    def _fix_now_note(
        self,
        issue: SonarIssue,
        context_signals: object,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        _ = issue, context_signals
        subject = self._history_subject(historical_context, history_source)
        fix_reference_note = self._fix_reference_note(historical_context)
        if historical_context.quick_fix_share >= 0.5:
            tendency = "similar cases of this rule were usually fixed quickly"
        elif historical_context.resolved_share >= 0.6:
            tendency = "similar cases of this rule were usually fixed"
        else:
            tendency = "this rule has been handled repeatedly in nearby code"

        return (
            f"{subject}, {tendency}.\n\n"
            "This looks like a reasonable fix to keep in this PR."
            f"{fix_reference_note}"
        )

    def _defer_decision_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        subject = self._history_subject(historical_context, history_source)
        fix_reference_note = self._fix_reference_note(historical_context)
        return (
            f"{subject}, similar cases of this rule often remained open once introduced.\n\n"
            "Since this issue is new in the PR, fix it now if possible; otherwise leave an explicit follow-up decision."
            f"{fix_reference_note}"
        )

    def _recurrence_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        subject = self._history_subject(historical_context, history_source)
        area = self._location_label(historical_context, history_source)
        return (
            f"{subject}, this rule has appeared repeatedly in {area}.\n\n"
            "Since this PR touches the surrounding code, avoid adding another instance of the same maintainability pattern."
        )

    @staticmethod
    def _fix_reference_note(historical_context: HistoricalContext) -> str:
        if not historical_context.fix_references:
            return ""

        reference = historical_context.fix_references[0]
        link = f"[PR #{reference.pr_number}]({reference.pr_url})"
        file_hint = (
            f" See the changed files for `{reference.file_path}`: {reference.file_url}."
            if reference.file_url is not None
            else ""
        )
        return (
            f"\n\nA similar fixed case is linked to {link}, with "
            f"{round(reference.confidence * 100)}% confidence from Sonar resolution history "
            f"and PR file evidence.{file_hint}"
        )

    def _history_subject(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        if self.is_local_history_source(history_source):
            return "In this repository"
        if historical_context.same_exact_path_matches >= 2:
            return "Among similar historical matches for this file path"
        return "Among similar historical matches for this rule"

    def _location_label(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        if self.is_local_history_source(history_source):
            if historical_context.same_exact_path_matches >= 2:
                return "this file"
            if historical_context.same_path_family_matches >= 3:
                return "this module area"
            return "this code area"
        if historical_context.same_exact_path_matches >= 2:
            return "matching file paths"
        if historical_context.same_path_family_matches >= 3:
            return "similar module paths"
        return "similar code areas"

    @staticmethod
    def _normalize_issue_message(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return message
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized

    @staticmethod
    def _pick_required_option(
        subject: SonarIssue | str,
        salt: str,
        options: VariantOptions,
    ) -> str:
        if isinstance(subject, SonarIssue):
            key = "|".join((subject.rule, subject.message, subject.location.path, salt))
        else:
            key = f"{subject}|{salt}"

        index = sum(ord(char) for char in key) % len(options)
        return options[index]
