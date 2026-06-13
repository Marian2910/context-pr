from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.request import urlopen

from contextpr.config import Settings
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    PullRequestFile,
    PullRequestRef,
)
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestRecord,
)

from .auth import GitHubAuth
from .client import GitHubApiClient
from .history import GitHubCommitHistorySync, GitHubRepositoryHistorySync
from .mapper import (
    classify_commit_message,
    map_commit_history,
    map_existing_review_comment,
    map_pull_request_file,
    map_pull_request_record,
    module_family,
    optional_string,
    review_comment_payload,
)
from .types import (
    GITHUB_HISTORY_PAGE_SIZE,
    LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
    LOCAL_GITHUB_SYNC_SOURCE,
    GitHubCommitHistorySyncResult,
    GitHubCommitHistorySyncResultPage,
    GitHubCommitSyncRecord,
    GitHubHistorySyncResult,
    GitHubHistorySyncResultPage,
    GitHubPullRequestSyncRecord,
)

logger = logging.getLogger(__name__)

__all__ = [
    "GITHUB_HISTORY_PAGE_SIZE",
    "LOCAL_GITHUB_COMMIT_SYNC_SOURCE",
    "LOCAL_GITHUB_SYNC_SOURCE",
    "GitHubClient",
    "GitHubCommitHistorySyncResult",
    "GitHubCommitHistorySyncResultPage",
    "GitHubCommitSyncRecord",
    "GitHubHistorySyncResult",
    "GitHubHistorySyncResultPage",
    "GitHubPullRequestSyncRecord",
]


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth = GitHubAuth(settings)
        self._api = GitHubApiClient(settings, self._auth, lambda request: urlopen(request))
        self._repository_history_sync = GitHubRepositoryHistorySync(self)
        self._commit_history_sync = GitHubCommitHistorySync(self)
        if self._settings.github_repository and self._auth.auth_mode != "none":
            logger.info("Configured GitHub client.", extra={"auth_mode": self._auth.auth_mode})

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
        payload = self._get_json_list(
            f"/repos/{pull_request.repository}/pulls/{pull_request.number}/files"
        )
        return [
            file_record
            for item in payload
            if isinstance(item, Mapping)
            if (file_record := map_pull_request_file(item)) is not None
        ]

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]:
        payload = self._get_json_list(
            f"/repos/{pull_request.repository}/pulls/{pull_request.number}/comments"
        )
        return [
            comment
            for item in payload
            if isinstance(item, Mapping)
            if (comment := map_existing_review_comment(item)) is not None
        ]

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

    def sync_repository_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int = GITHUB_HISTORY_PAGE_SIZE,
    ) -> GitHubHistorySyncResult:
        return self._repository_history_sync.sync_repository_history(
            store=store,
            repository_key=repository_key,
            page_size=page_size,
        )

    def sync_commit_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int = GITHUB_HISTORY_PAGE_SIZE,
    ) -> GitHubCommitHistorySyncResult:
        return self._commit_history_sync.sync_commit_history(
            store=store,
            repository_key=repository_key,
            page_size=page_size,
        )

    def _sync_pull_request_page(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        payload: list[object],
        previous_cursor: str | None,
        latest_update: str | None,
    ) -> GitHubHistorySyncResultPage:
        return self._repository_history_sync.sync_pull_request_page(
            store=store,
            repository_key=repository_key,
            payload=payload,
            previous_cursor=previous_cursor,
            latest_update=latest_update,
        )

    def _sync_pull_request_record(
        self,
        store: HistoryStore,
        repository_key: str,
        item: Mapping[str, object],
    ) -> GitHubPullRequestSyncRecord | None:
        return self._repository_history_sync.sync_pull_request_record(
            store,
            repository_key,
            dict(item),
        )

    def _sync_commit_page(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        payload: list[object],
        previous_cursor: str | None,
    ) -> GitHubCommitHistorySyncResultPage:
        return self._commit_history_sync.sync_commit_page(
            store=store,
            repository_key=repository_key,
            payload=payload,
            previous_cursor=previous_cursor,
        )

    def _sync_commit_record(
        self,
        store: HistoryStore,
        repository_key: str,
        commit_sha: str,
    ) -> GitHubCommitSyncRecord | None:
        return self._commit_history_sync.sync_commit_record(store, repository_key, commit_sha)

    def _pull_request_ref(self, repository_key: str, pr_number: int) -> PullRequestRef:
        return PullRequestRef(repository=repository_key, number=pr_number)

    def _require_configured(self) -> None:
        self._api.require_configured()

    def _get_json_list(self, path: str) -> list[Any]:
        payload = self._get_json(path)
        return payload if isinstance(payload, list) else []

    def _get_json_mapping(self, path: str) -> Mapping[str, object]:
        payload = self._get_json(path)
        return payload if isinstance(payload, Mapping) else {}

    def _get_json(self, path: str) -> object:
        return self._api.get_json(path)

    def _send_json(
        self,
        *,
        path: str,
        method: str,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        self._api.send_json(path=path, method=method, payload=payload)

    @staticmethod
    def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
        return optional_string(payload, key)

    @staticmethod
    def _map_pull_request_record(payload: Mapping[str, object]) -> PullRequestRecord | None:
        return map_pull_request_record(payload)

    @staticmethod
    def _map_commit_history(
        payload: Mapping[str, object],
    ) -> tuple[GitCommitRecord, tuple[GitFileTouchRecord, ...]] | None:
        return map_commit_history(payload)

    @staticmethod
    def _classify_commit_message(message: str) -> str:
        return classify_commit_message(message)

    @staticmethod
    def _module_family(file_path: str) -> str | None:
        return module_family(file_path)

    @staticmethod
    def _review_comment_payload(comment: GitHubReviewComment) -> dict[str, object]:
        return review_comment_payload(comment)
