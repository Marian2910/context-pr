"""GitHub integration placeholders."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from contextpr.config import Settings
from contextpr.integrations.github_auth import GitHubAuth
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    PullRequestFile,
    PullRequestRef,
)

logger = logging.getLogger(__name__)


class GitHubClient:
    """Placeholder client for GitHub pull request interactions."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the client with application settings."""
        self._settings = settings
        self._auth = GitHubAuth(settings)
        if self._settings.github_repository and self._auth.auth_mode != "none":
            logger.info("Configured GitHub client.", extra={"auth_mode": self._auth.auth_mode})

    def is_configured(self) -> bool:
        """Return whether the client has enough configuration to operate."""
        return self._settings.github_enabled

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
        """Fetch the list of changed files for a pull request."""
        self._settings.require("github_repository")
        self._auth.require_configured()

        request = Request(
            url=self._api_url(f"/repos/{pull_request.repository}/pulls/{pull_request.number}/files"),
            headers=self._headers(),
        )

        with urlopen(request) as response:
            payload = json.load(response)

        if not isinstance(payload, list):
            return []

        files: list[PullRequestFile] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue

            filename = item.get("filename")
            status = item.get("status")
            patch = item.get("patch")
            if isinstance(filename, str) and isinstance(status, str):
                files.append(
                    PullRequestFile(
                        path=filename,
                        status=status,
                        patch=patch if isinstance(patch, str) else None,
                    )
                )

        return files

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]:
        """Fetch existing inline review comments for a pull request."""
        self._settings.require("github_repository")
        self._auth.require_configured()

        request = Request(
            url=self._api_url(
                f"/repos/{pull_request.repository}/pulls/{pull_request.number}/comments"
            ),
            headers=self._headers(),
        )

        with urlopen(request) as response:
            payload = json.load(response)

        if not isinstance(payload, list):
            return []

        comments: list[ExistingReviewComment] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue

            comment_id = item.get("id")
            path = item.get("path")
            body = item.get("body")
            line = item.get("line")
            user = item.get("user")
            author_login = user.get("login") if isinstance(user, Mapping) else None
            if (
                isinstance(comment_id, int)
                and isinstance(path, str)
                and isinstance(body, str)
                and (line is None or isinstance(line, int))
                and isinstance(author_login, str)
            ):
                comments.append(
                    ExistingReviewComment(
                        comment_id=comment_id,
                        path=path,
                        line=line,
                        body=body,
                        author_login=author_login,
                    )
                )

        return comments

    def create_review(
        self,
        *,
        pull_request: PullRequestRef,
        comments: list[GitHubReviewComment],
    ) -> None:
        """Create a pull request review containing inline comments."""
        self._settings.require("github_repository")
        self._auth.require_configured()

        body = json.dumps(
            {
                "event": "COMMENT",
                "comments": [
                    {
                        "path": comment.path,
                        "line": comment.line,
                        "side": comment.side,
                        "body": comment.body,
                    }
                    for comment in comments
                ],
            }
        ).encode("utf-8")
        request = Request(
            url=self._api_url(f"/repos/{pull_request.repository}/pulls/{pull_request.number}/reviews"),
            headers=self._headers(),
            data=body,
            method="POST",
        )

        with urlopen(request):
            return None

    def delete_review_comment(self, comment_id: int) -> None:
        """Delete an existing pull request review comment."""
        self._settings.require("github_repository")
        self._auth.require_configured()

        request = Request(
            url=self._api_url(f"/repos/{self._settings.github_repository}/pulls/comments/{comment_id}"),
            headers=self._headers(),
            method="DELETE",
        )

        with urlopen(request):
            return None

    def get_authenticated_user_login(self) -> str:
        """Return the visible login associated with the configured GitHub identity."""
        self._settings.require("github_repository")
        self._auth.require_configured()
        return self._auth.get_actor_login()

    def _api_url(self, path: str) -> str:
        """Build a full GitHub API URL from a relative path."""
        base_url = self._settings.github_api_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        """Build standard GitHub REST API headers."""
        token = self._auth.get_token()
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
