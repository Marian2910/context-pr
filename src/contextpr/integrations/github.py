from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any
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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth = GitHubAuth(settings)
        if self._settings.github_repository and self._auth.auth_mode != "none":
            logger.info("Configured GitHub client.", extra={"auth_mode": self._auth.auth_mode})

    def is_configured(self) -> bool:
        return self._settings.github_enabled

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
        payload = self._get_json_list(
            f"/repos/{pull_request.repository}/pulls/{pull_request.number}/files"
        )

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
        payload = self._get_json_list(
            f"/repos/{pull_request.repository}/pulls/{pull_request.number}/comments"
        )

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
        self._send_json(
            path=f"/repos/{pull_request.repository}/pulls/{pull_request.number}/reviews",
            method="POST",
            payload={
                "event": "COMMENT",
                "comments": [self._review_comment_payload(comment) for comment in comments],
            },
        )

    def delete_review_comment(self, comment_id: int) -> None:
        self._send_json(
            path=f"/repos/{self._settings.github_repository}/pulls/comments/{comment_id}",
            method="DELETE",
        )

    def get_authenticated_user_login(self) -> str:
        self._require_configured()
        return self._auth.get_actor_login()

    def _require_configured(self) -> None:
        self._settings.require("github_repository")
        self._auth.require_configured()

    def _get_json_list(self, path: str) -> list[Any]:
        payload = self._get_json(path)
        return payload if isinstance(payload, list) else []

    def _get_json(self, path: str) -> object:
        self._require_configured()
        with urlopen(self._request(path)) as response:
            return json.load(response)

    def _send_json(
        self,
        *,
        path: str,
        method: str,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        self._require_configured()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        with urlopen(self._request(path, method=method, data=body)):
            return None

    def _request(
        self,
        path: str,
        *,
        method: str | None = None,
        data: bytes | None = None,
    ) -> Request:
        return Request(
            url=self._api_url(path),
            headers=self._headers(),
            data=data,
            method=method,
        )

    def _api_url(self, path: str) -> str:
        base_url = self._settings.github_api_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        token = self._auth.get_token()
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _review_comment_payload(comment: GitHubReviewComment) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": comment.path,
            "line": comment.line,
            "side": comment.side,
            "body": comment.body,
        }
        if comment.start_line is not None:
            payload["start_line"] = comment.start_line
            payload["start_side"] = comment.start_side or comment.side
        return payload
