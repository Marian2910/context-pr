from __future__ import annotations

from contextpr.models import SonarIssue


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

    @staticmethod
    def _normalize_issue_message(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return message
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized
