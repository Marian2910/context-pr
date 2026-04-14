from __future__ import annotations

from contextpr.models import SonarIssue


class NLPEnrichmentService:
    """Placeholder service for composing developer-facing explanations."""

    def draft_inline_comment(self, issue: SonarIssue, history_summary: str) -> str:
        """Draft a contextual inline comment for a pull request finding."""
        raise NotImplementedError("NLP-based comment drafting is not implemented yet.")
