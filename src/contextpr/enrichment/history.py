"""Historical context enrichment placeholders."""

from __future__ import annotations

from contextpr.models import SonarIssue


class HistoryEnrichmentService:
    """Placeholder service for collecting historical context for issues."""

    def summarize_issue_history(self, issue: SonarIssue) -> str:
        """Build a short historical summary for an issue."""
        raise NotImplementedError("Issue history enrichment is not implemented yet.")
