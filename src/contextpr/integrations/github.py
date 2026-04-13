"""GitHub integration placeholders."""

from __future__ import annotations

from contextpr.config import Settings
from contextpr.models import PullRequestRef


class GitHubClient:
    """Placeholder client for GitHub pull request interactions."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the client with application settings."""
        self._settings = settings

    def is_configured(self) -> bool:
        """Return whether the client has enough configuration to operate."""
        return self._settings.github_enabled

    def post_inline_comment(
        self,
        *,
        pull_request: PullRequestRef,
        path: str,
        line: int,
        body: str,
    ) -> None:
        """Post an inline pull request comment.

        The concrete GitHub REST or GraphQL implementation will be added later.
        """
        raise NotImplementedError("GitHub comment posting is not implemented yet.")

    def list_existing_review_threads(self, pull_request: PullRequestRef) -> list[str]:
        """List existing review threads for the pull request.

        This will later support de-duplication and update flows.
        """
        raise NotImplementedError("GitHub review thread retrieval is not implemented yet.")
