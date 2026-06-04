from __future__ import annotations

from contextpr.models import SonarIssue

LOCAL_HISTORY_SOURCES = frozenset(
    {
        "local_sonar",
        "local_git",
        "local_prs",
        "local_review_comments",
    }
)


class DeterministicGuidanceMessageService:
    def build_explanation(
        self,
        issue: SonarIssue,
        context_signals: object | None = None,
        historical_context: object | None = None,
        history_source: str | None = None,
    ) -> str:
        _ = context_signals, historical_context, history_source
        return self._normalize_issue_message(issue.message)

    def build_next_step(
        self,
        comment_intent: str,
        context_signals: object | None = None,
        historical_context: object | None = None,
        history_source: str | None = None,
    ) -> str | None:
        _ = comment_intent, context_signals, historical_context, history_source
        return None

    def build_evidence_note(
        self,
        issue: SonarIssue,
        comment_intent: str,
        context_signals: object | None = None,
        historical_context: object | None = None,
        history_source: str | None = None,
    ) -> str | None:
        _ = issue, comment_intent, context_signals, historical_context, history_source
        return None

    @staticmethod
    def _normalize_issue_message(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return message
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized

    @staticmethod
    def is_local_history_source(history_source: str | None) -> bool:
        return history_source in LOCAL_HISTORY_SOURCES
