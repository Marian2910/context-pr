from __future__ import annotations

from contextpr.enrichment.history import HistoricalContext
from contextpr.models import SonarIssue

LOCAL_HISTORY_SOURCES = {
    "local_sonar",
    "local_git",
    "local_prs",
    "local_review_comments",
}
DATASET_HISTORY_SOURCES = {"global_dataset"}
SUPPORTED_HISTORY_SOURCES = LOCAL_HISTORY_SOURCES | DATASET_HISTORY_SOURCES
CROSS_REPOSITORY_SUBJECT = "In similar issues from other repositories"
LOCAL_REPOSITORY_SUBJECT = "In this repository"
CAUTION_NOTE = "Review the surrounding code before changing it."
FIX_NOW_NOTE = "This seems worth fixing in this PR."
DEFER_NOTE = (
    "This may not be worth forcing in this PR unless you're already changing "
    "the surrounding code."
)
REVIEW_RECURRENCE_NOTE = "This keeps coming up in review, so it's probably worth a closer look."
DATASET_RECURRENCE_NOTE = (
    "This seems to come up repeatedly in similar code, not as a one-off warning."
)
LOCAL_RECURRENCE_NOTE = "This seems to be a repeated local issue, not a one-time warning."


class DeterministicGuidanceMessageService:
    def build_explanation(
        self,
        issue: SonarIssue,
        context_signals: object | None = None,
        historical_context: HistoricalContext | None = None,
        history_source: str | None = None,
    ) -> str:
        _ = context_signals, historical_context, history_source
        return self._normalize_issue_message(issue.message)

    def build_next_step(
        self,
        issue_pattern: str,
        context_signals: object | None = None,
        historical_context: HistoricalContext | None = None,
        history_source: str | None = None,
    ) -> str | None:
        if issue_pattern in self._behavior_sensitive_patterns():
            return CAUTION_NOTE
        if issue_pattern == "general_review" and historical_context is not None:
            _ = context_signals, history_source
            return (
                "If this is a small, local fix, address it in this PR. "
                "Otherwise, make the follow-up explicit."
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

        if history_source not in SUPPORTED_HISTORY_SOURCES:
            return None

        if issue_pattern == "worth_fixing_now":
            return self._fix_now_note(issue, context_signals, historical_context, history_source)
        if issue_pattern == "decide_before_deferring":
            return self._defer_decision_note(historical_context, history_source)
        if issue_pattern == "recurs_here":
            return self._recurrence_note(historical_context, history_source)
        if issue_pattern in self._behavior_sensitive_patterns():
            return self._inspect_before_changing_note(historical_context, history_source)
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
        if historical_context.dominant_disposition in {"persistent", "accepted"}:
            return "persistent_debt"
        if historical_context.fix_references or historical_context.resolved_share >= 0.6:
            return "usually_fixed"
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
        if history_source not in SUPPORTED_HISTORY_SOURCES:
            return None

        focus = self.maintainability_focus(historical_context)
        if focus == "persistent_debt":
            return self._defer_decision_note(historical_context, history_source)
        if focus == "usually_fixed":
            return self._fix_reference_note(historical_context).lstrip("\n") or None
        if focus == "later_refactor":
            if history_source == "global_dataset" and self._has_hotspot(historical_context):
                return self._recurrence_note(historical_context, history_source)
            return None
        if focus == "accumulating_hotspot":
            return self._recurrence_note(historical_context, history_source)
        return None

    def _fix_now_note(
        self,
        issue: SonarIssue,
        context_signals: object,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        _ = issue, context_signals
        fix_reference_note = self._fix_reference_note(historical_context)
        summary = self._trend_summary(
            historical_context,
            history_source,
            trend="fixed",
        )
        return self._compose_note(summary, FIX_NOW_NOTE, fix_reference_note)

    def _defer_decision_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        fix_reference_note = self._fix_reference_note(historical_context)
        summary = self._trend_summary(
            historical_context,
            history_source,
            trend="persistent",
        )
        return self._compose_note(summary, DEFER_NOTE, CAUTION_NOTE, fix_reference_note)

    def _recurrence_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        summary = self._recurrence_summary(historical_context, history_source)
        follow_up = self._recurrence_follow_up(historical_context, history_source)
        return f"{summary}\n\n{follow_up}"

    def _inspect_before_changing_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str | None:
        note = self._select_local_history_note(historical_context, history_source)
        fix_reference_note = self._fix_reference_note(historical_context)
        if note is None:
            stripped_reference = fix_reference_note.lstrip("\n")
            if not stripped_reference:
                return None
            return self._compose_note(CAUTION_NOTE, stripped_reference)
        if CAUTION_NOTE in note:
            return f"{note}{fix_reference_note}"
        return self._compose_note(note, CAUTION_NOTE, fix_reference_note)

    @staticmethod
    def _fix_reference_note(historical_context: HistoricalContext) -> str:
        if not historical_context.fix_references:
            return ""

        reference = historical_context.fix_references[0]
        link = f"[PR #{reference.pr_number}]({reference.pr_url})"
        evidence_lines = "\n".join(
            f"- {evidence}"
            for evidence in reference.evidence
        )
        previous_fix = reference.file_url or reference.pr_url
        return (
            f"\n\nA similar fixed case is linked to {link}, with "
            f"{round(reference.confidence * 100)}% confidence from Sonar resolution history.\n\n"
            "Why this match is shown:\n"
            f"{evidence_lines}\n\n"
            "Previous fix:\n"
            f"{previous_fix}"
        )

    def _select_local_history_note(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str | None:
        if historical_context.persistent_share >= 0.6 or historical_context.accepted_share >= 0.5:
            return self._compose_note(
                self._trend_summary(historical_context, history_source, trend="persistent"),
                DEFER_NOTE,
            )
        if historical_context.quick_fix_share >= 0.5 or historical_context.resolved_share >= 0.6:
            return self._compose_note(
                self._trend_summary(historical_context, history_source, trend="fixed"),
                CAUTION_NOTE,
            )
        if self._has_hotspot(historical_context):
            return self._recurrence_note(historical_context, history_source)
        return None

    def _trend_summary(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
        *,
        trend: str,
    ) -> str:
        subject = self._history_subject(historical_context, history_source)
        area = self._location_label(historical_context, history_source)
        if trend == "fixed":
            base = (
                "similar cases of this rule were usually addressed quickly"
                if historical_context.quick_fix_share >= 0.5
                else "similar cases of this rule were usually addressed"
            )
            if self._has_hotspot(historical_context):
                return f"{subject}, this rule has already appeared multiple times in {area} and was usually addressed."
            return f"{subject}, {base}."

        if self._has_hotspot(historical_context):
            return f"{subject}, this rule has already appeared multiple times in {area} and was often left open."
        return f"{subject}, similar cases of this rule were often left open."

    def _recurrence_summary(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        subject = self._history_subject(historical_context, history_source)
        area = self._location_label(historical_context, history_source)
        if history_source == "local_review_comments":
            return f"{subject}, this rule has come up repeatedly in review comments for {area}."
        if historical_context.fix_references or historical_context.resolved_share >= 0.3:
            return f"{subject}, this rule has appeared multiple times in {area} before, and some past cases were addressed."
        return f"{subject}, this issue has appeared multiple times in {area} before but was not addressed."

    def _recurrence_follow_up(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        _ = historical_context
        if history_source == "local_review_comments":
            return REVIEW_RECURRENCE_NOTE
        if history_source == "global_dataset":
            return DATASET_RECURRENCE_NOTE
        return LOCAL_RECURRENCE_NOTE

    @staticmethod
    def _has_hotspot(historical_context: HistoricalContext) -> bool:
        return (
            historical_context.same_exact_path_matches >= 2
            or historical_context.same_path_family_matches >= 3
        )

    def _history_subject(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        _ = historical_context
        if history_source == "global_dataset":
            return CROSS_REPOSITORY_SUBJECT
        return LOCAL_REPOSITORY_SUBJECT

    def _location_label(
        self,
        historical_context: HistoricalContext,
        history_source: str | None,
    ) -> str:
        if history_source == "global_dataset":
            if historical_context.same_exact_path_matches >= 2:
                return "similar files"
            if historical_context.same_path_family_matches >= 3:
                return "similar module areas"
            return "similar code areas"
        if historical_context.same_exact_path_matches >= 2:
            return "this file"
        if historical_context.same_path_family_matches >= 3:
            return "this module area"
        return "this code area"

    @staticmethod
    def _normalize_issue_message(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return message
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized

    @staticmethod
    def _behavior_sensitive_patterns() -> frozenset[str]:
        return frozenset(
            {
                "inspect_before_changing",
                "behavior_sensitive_cleanup",
                "behavior_risk",
            }
        )

    @staticmethod
    def _compose_note(*parts: str) -> str:
        normalized_parts = [part.strip() for part in parts if part and part.strip()]
        return "\n\n".join(normalized_parts)
