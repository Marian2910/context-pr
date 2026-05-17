from __future__ import annotations

from contextpr.enrichment.history import (
    DISPOSITION_LABELS,
    MAINTENANCE_LABELS,
    HistoricalContext,
)
from contextpr.models import SonarIssue

VariantOptions = tuple[str, str, str, str]

HOTSPOT_FILE_MATCHES = 2
HOTSPOT_MODULE_MATCHES = 3
HOTSPOT_MODULE_SHARE = 0.5
MIN_HISTORY_SHARE = 0.5

EXPLANATION_OPTIONS: dict[str, VariantOptions] = {
    "behavior_sensitive_change": (
        "This may affect runtime behavior, so verify the intended outcome before editing it.",
        "Review this path carefully before changing it because the current behavior may be intentional.",
        "Validate the expected behavior here before rewriting the code around it.",
        "Check what behavior this code is preserving before you refactor it.",
    ),
    "behavior_sensitive_cleanup": (
        "This warning points to behavior-sensitive cleanup, so preserve the current result when you simplify it.",
        "This cleanup touches control flow or captured state, so confirm the current behavior before simplifying it.",
        "Treat this as a behavior-sensitive cleanup and make sure the simplification keeps the current outcome intact.",
        "Simplify this carefully because the current structure may be preserving runtime behavior.",
    ),
}

NEXT_STEP_OPTIONS: dict[str, VariantOptions] = {
    "behavior_sensitive_change": (
        "Verify the surrounding logic before changing the flagged code path.",
        "Check the surrounding logic to confirm the current behavior is really intended.",
        "Validate the code path against the expected behavior before changing it.",
        "Review the flagged logic path against the expected behavior before editing it.",
    ),
    "behavior_sensitive_cleanup": (
        "Make the cleanup in a way that binds or preserves the current runtime state before simplifying the structure.",
        "Apply the simplification only after you make the affected state explicit enough to preserve the current behavior.",
        "Restructure this cleanup so the current runtime state is preserved instead of relying on incidental control flow.",
        "Simplify it only after you make the behavior-carrying state explicit and verify the affected path.",
    ),
}


class DeterministicGuidanceMessageService:
    def build_explanation(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str:
        if issue_pattern == "behavior_sensitive_cleanup":
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS["behavior_sensitive_cleanup"],
            )

        if issue.issue_type == "BUG":
            return self._pick_required_option(
                issue,
                "explanation",
                EXPLANATION_OPTIONS["behavior_sensitive_change"],
            )

        direct_explanation = self._issue_specific_maintainability_explanation(
            issue,
            issue_pattern,
        )
        if direct_explanation is not None:
            return direct_explanation

        assert historical_context is not None
        return self._build_maintainability_explanation(historical_context, history_source)

    def build_next_step(
        self,
        issue: SonarIssue,
        issue_pattern: str,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str | None:
        if issue_pattern == "behavior_sensitive_cleanup":
            return self._pick_required_option(
                issue,
                "next_step",
                NEXT_STEP_OPTIONS["behavior_sensitive_cleanup"],
            )

        if issue.issue_type == "BUG":
            return self._pick_required_option(
                issue,
                "next_step",
                NEXT_STEP_OPTIONS["behavior_sensitive_change"],
            )

        if issue.issue_type == "CODE_SMELL":
            return None

        assert historical_context is not None
        return self._build_maintainability_next_step(historical_context, history_source)

    def build_evidence_note(
        self,
        historical_context: HistoricalContext | None,
        history_source: str | None,
    ) -> str | None:
        if historical_context is None:
            return None
        return self._build_maintainability_evidence_note(historical_context, history_source)

    @staticmethod
    def is_local_history_source(history_source: str | None) -> bool:
        return history_source in {
            "local_sonar",
            "local_git",
            "local_prs",
            "local_review_comments",
        }

    def maintainability_focus(self, historical_context: HistoricalContext) -> str:
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

    def _issue_specific_maintainability_explanation(
        self,
        issue: SonarIssue,
        issue_pattern: str,
    ) -> str | None:
        if issue_pattern == "structural_simplification":
            return (
                "This structure can be simplified, but first confirm that the current separation "
                "is not carrying distinct behavior or intent."
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

    def _build_maintainability_explanation(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        location_subject = self._location_subject(historical_context, history_source)
        focus = self.maintainability_focus(historical_context)
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
        return f"Similar cases in {location_subject} have needed follow-up cleanup more than once."

    def _build_maintainability_next_step(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        _ = history_source
        focus = self.maintainability_focus(historical_context)
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
            return "Use this touchpoint to simplify or narrow the smell while the code is already open."
        return "Consider addressing it in this change or leaving an explicit note if it is staying for now."

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

    def _evidence_subject(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str | None:
        if self.is_local_history_source(history_source):
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

    def _evidence_pattern_clause(self, historical_context: HistoricalContext) -> str | None:
        disposition_distribution = historical_context.disposition_distribution
        if disposition_distribution:
            if self.is_split_distribution(
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

        if self.is_split_distribution(
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
        focus = self.maintainability_focus(historical_context)
        if focus == "behavior_sensitive":
            return "inspect the surrounding logic before simplifying it"
        if focus == "persistent_debt":
            if self.is_local_history_source(history_source):
                return "decide explicitly whether to fix it now or leave it for follow-up"
            return "it is worth deciding explicitly whether this should be fixed now"
        if focus in {"later_refactor", "accumulating_hotspot"}:
            if self.is_local_history_source(history_source):
                return "this is probably worth resolving in this PR if the cleanup is small"
            return None
        return None

    def _location_subject(
        self,
        historical_context: HistoricalContext,
        history_source: str | None = None,
    ) -> str:
        if self.is_local_history_source(history_source):
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
