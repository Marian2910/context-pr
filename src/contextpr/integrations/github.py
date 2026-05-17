from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    SyncStateRecord,
)

logger = logging.getLogger(__name__)
LOCAL_GITHUB_SYNC_SOURCE = "local_github_history"
LOCAL_GITHUB_COMMIT_SYNC_SOURCE = "local_git_history"
GITHUB_HISTORY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class GitHubHistorySyncResult:
    repository_key: str
    pages_fetched: int
    pull_requests_seen: int
    pull_requests_upserted: int
    files_recorded: int
    review_comments_recorded: int
    latest_update: str | None


@dataclass(frozen=True, slots=True)
class GitHubCommitHistorySyncResult:
    repository_key: str
    pages_fetched: int
    commits_seen: int
    commits_upserted: int
    touches_recorded: int
    latest_commit_sha: str | None
    latest_authored_at: str | None


@dataclass(frozen=True, slots=True)
class GitHubHistorySyncResultPage:
    should_stop: bool
    pull_requests_seen: int
    pull_requests_upserted: int
    files_recorded: int
    review_comments_recorded: int
    latest_update: str | None


@dataclass(frozen=True, slots=True)
class GitHubPullRequestSyncRecord:
    files_recorded: int
    review_comments_recorded: int


@dataclass(frozen=True, slots=True)
class GitHubCommitHistorySyncResultPage:
    should_stop: bool
    commits_seen: int
    commits_upserted: int
    touches_recorded: int
    latest_commit_sha: str | None
    latest_authored_at: str | None


@dataclass(frozen=True, slots=True)
class GitHubCommitSyncRecord:
    commit_sha: str
    authored_at: str | None
    touches_recorded: int


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

    def sync_repository_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int = GITHUB_HISTORY_PAGE_SIZE,
    ) -> GitHubHistorySyncResult:
        with store.acquire_repository_lock(repository_key):
            previous_state = store.get_sync_state(repository_key, LOCAL_GITHUB_SYNC_SOURCE)
            previous_cursor = previous_state.cursor if previous_state is not None else None
            page_number = 1
            pages_fetched = 0
            pull_requests_seen = 0
            pull_requests_upserted = 0
            files_recorded = 0
            review_comments_recorded = 0
            latest_update = previous_cursor

            while True:
                payload = self._get_json_list(
                    f"/repos/{repository_key}/pulls?state=all&sort=updated&direction=desc&per_page={page_size}&page={page_number}"
                )
                pages_fetched += 1
                if not payload:
                    break

                page_result = self._sync_pull_request_page(
                    store=store,
                    repository_key=repository_key,
                    payload=payload,
                    previous_cursor=previous_cursor,
                    latest_update=latest_update,
                )
                pull_requests_seen += page_result.pull_requests_seen
                pull_requests_upserted += page_result.pull_requests_upserted
                files_recorded += page_result.files_recorded
                review_comments_recorded += page_result.review_comments_recorded
                latest_update = page_result.latest_update

                if latest_update is not None:
                    store.upsert_sync_state(
                        SyncStateRecord(
                            repository_key=repository_key,
                            source_name=LOCAL_GITHUB_SYNC_SOURCE,
                            cursor=latest_update,
                            updated_at=latest_update,
                        )
                    )

                if page_result.should_stop or len(payload) < page_size:
                    break
                page_number += 1

            return GitHubHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=pages_fetched,
                pull_requests_seen=pull_requests_seen,
                pull_requests_upserted=pull_requests_upserted,
                files_recorded=files_recorded,
                review_comments_recorded=review_comments_recorded,
                latest_update=latest_update,
            )

    def sync_commit_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int = GITHUB_HISTORY_PAGE_SIZE,
    ) -> GitHubCommitHistorySyncResult:
        with store.acquire_repository_lock(repository_key):
            previous_state = store.get_sync_state(repository_key, LOCAL_GITHUB_COMMIT_SYNC_SOURCE)
            previous_cursor = previous_state.cursor if previous_state is not None else None
            page_number = 1
            pages_fetched = 0
            commits_seen = 0
            commits_upserted = 0
            touches_recorded = 0
            latest_commit_sha = previous_cursor
            latest_authored_at = previous_state.updated_at if previous_state is not None else None

            while True:
                payload = self._get_json_list(
                    f"/repos/{repository_key}/commits?per_page={page_size}&page={page_number}"
                )
                pages_fetched += 1
                if not payload:
                    break

                page_result = self._sync_commit_page(
                    store=store,
                    repository_key=repository_key,
                    payload=payload,
                    previous_cursor=previous_cursor,
                )
                commits_seen += page_result.commits_seen
                commits_upserted += page_result.commits_upserted
                touches_recorded += page_result.touches_recorded
                if page_result.latest_commit_sha is not None:
                    latest_commit_sha = page_result.latest_commit_sha
                    latest_authored_at = page_result.latest_authored_at

                if latest_commit_sha is not None:
                    store.upsert_sync_state(
                        SyncStateRecord(
                            repository_key=repository_key,
                            source_name=LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
                            cursor=latest_commit_sha,
                            updated_at=latest_authored_at,
                        )
                    )

                if page_result.should_stop or len(payload) < page_size:
                    break
                page_number += 1

            return GitHubCommitHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=pages_fetched,
                commits_seen=commits_seen,
                commits_upserted=commits_upserted,
                touches_recorded=touches_recorded,
                latest_commit_sha=latest_commit_sha,
                latest_authored_at=latest_authored_at,
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
        pull_requests_seen = 0
        pull_requests_upserted = 0
        files_recorded = 0
        review_comments_recorded = 0
        should_stop = False

        for item in payload:
            if not isinstance(item, Mapping):
                continue
            pull_requests_seen += 1
            updated_at = self._optional_string(item, "updated_at")
            if previous_cursor and updated_at and updated_at <= previous_cursor:
                should_stop = True
                continue
            if updated_at and (latest_update is None or updated_at > latest_update):
                latest_update = updated_at

            synced = self._sync_pull_request_record(store, repository_key, item)
            if synced is None:
                continue
            pull_requests_upserted += 1
            files_recorded += synced.files_recorded
            review_comments_recorded += synced.review_comments_recorded

        return GitHubHistorySyncResultPage(
            should_stop=should_stop,
            pull_requests_seen=pull_requests_seen,
            pull_requests_upserted=pull_requests_upserted,
            files_recorded=files_recorded,
            review_comments_recorded=review_comments_recorded,
            latest_update=latest_update,
        )

    def _sync_pull_request_record(
        self,
        store: HistoryStore,
        repository_key: str,
        item: Mapping[str, object],
    ) -> GitHubPullRequestSyncRecord | None:
        if (record := self._map_pull_request_record(item)) is None:
            return None

        pull_request = PullRequestRef(repository=repository_key, number=record.pr_number)
        files = tuple(
            PullRequestFileRecord(pr_number=record.pr_number, file_path=file_record.path)
            for file_record in self.get_pull_request_files(pull_request)
        )
        review_comments = tuple(
            PullRequestReviewCommentRecord(
                comment_id=comment.comment_id,
                pr_number=record.pr_number,
                body=comment.body,
                file_path=comment.path,
                line=comment.line,
                author_role=comment.author_login,
            )
            for comment in self.list_existing_review_comments(pull_request)
        )
        store.upsert_pull_request(
            repository_key,
            record,
            files=files,
            review_comments=review_comments,
        )
        return GitHubPullRequestSyncRecord(
            files_recorded=len(files),
            review_comments_recorded=len(review_comments),
        )

    def _sync_commit_page(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        payload: list[object],
        previous_cursor: str | None,
    ) -> GitHubCommitHistorySyncResultPage:
        commits_seen = 0
        commits_upserted = 0
        touches_recorded = 0
        latest_commit_sha: str | None = None
        latest_authored_at: str | None = None
        should_stop = False

        for item in payload:
            if not isinstance(item, Mapping):
                continue
            commit_sha = self._optional_string(item, "sha")
            if commit_sha is None:
                continue
            commits_seen += 1
            if previous_cursor and commit_sha == previous_cursor:
                should_stop = True
                break

            synced = self._sync_commit_record(store, repository_key, commit_sha)
            if synced is None:
                continue
            commits_upserted += 1
            touches_recorded += synced.touches_recorded
            if latest_commit_sha is None:
                latest_commit_sha = synced.commit_sha
                latest_authored_at = synced.authored_at

        return GitHubCommitHistorySyncResultPage(
            should_stop=should_stop,
            commits_seen=commits_seen,
            commits_upserted=commits_upserted,
            touches_recorded=touches_recorded,
            latest_commit_sha=latest_commit_sha,
            latest_authored_at=latest_authored_at,
        )

    def _sync_commit_record(
        self,
        store: HistoryStore,
        repository_key: str,
        commit_sha: str,
    ) -> GitHubCommitSyncRecord | None:
        commit_payload = self._get_json_mapping(f"/repos/{repository_key}/commits/{commit_sha}")
        mapped = self._map_commit_history(commit_payload)
        if mapped is None:
            return None

        commit_record, touches = mapped
        store.upsert_git_commit(repository_key, commit_record, touches=touches)
        return GitHubCommitSyncRecord(
            commit_sha=commit_record.commit_sha,
            authored_at=commit_record.authored_at,
            touches_recorded=len(touches),
        )

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

    def _get_json_mapping(self, path: str) -> Mapping[str, object]:
        payload = self._get_json(path)
        return payload if isinstance(payload, Mapping) else {}

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
    def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _map_pull_request_record(self, payload: Mapping[str, object]) -> PullRequestRecord | None:
        pr_number = payload.get("number")
        title = payload.get("title")
        if not isinstance(pr_number, int) or not isinstance(title, str):
            return None
        return PullRequestRecord(
            pr_number=pr_number,
            title=title,
            body=self._optional_string(payload, "body"),
            state=self._optional_string(payload, "state"),
            merged_at=self._optional_string(payload, "merged_at"),
            updated_at=self._optional_string(payload, "updated_at"),
        )

    def _map_commit_history(
        self,
        payload: Mapping[str, object],
    ) -> tuple[GitCommitRecord, tuple[GitFileTouchRecord, ...]] | None:
        commit_sha = self._optional_string(payload, "sha")
        commit_info = payload.get("commit")
        if commit_sha is None or not isinstance(commit_info, Mapping):
            return None

        commit_message = self._optional_string(commit_info, "message")
        author_info = commit_info.get("author")
        authored_at = (
            self._optional_string(author_info, "date")
            if isinstance(author_info, Mapping)
            else None
        )
        if commit_message is None or authored_at is None:
            return None

        files_payload = payload.get("files")
        touches: tuple[GitFileTouchRecord, ...] = ()
        if isinstance(files_payload, list):
            touches = tuple(
                GitFileTouchRecord(
                    commit_sha=commit_sha,
                    file_path=filename,
                    module_family=self._module_family(filename),
                )
                for filename in (
                    self._optional_string(item, "filename")
                    for item in files_payload
                    if isinstance(item, Mapping)
                )
                if filename is not None
            )

        return (
            GitCommitRecord(
                commit_sha=commit_sha,
                authored_at=authored_at,
                message=commit_message,
                classification=self._classify_commit_message(commit_message),
            ),
            touches,
        )

    @staticmethod
    def _classify_commit_message(message: str) -> str:
        normalized = message.strip().lower()
        if any(token in normalized for token in ("refactor", "cleanup", "simplif")):
            return "refactor"
        if any(token in normalized for token in ("fix", "bug", "hotfix")):
            return "fix"
        if any(token in normalized for token in ("test", "spec")):
            return "test"
        if any(token in normalized for token in ("doc", "readme")):
            return "docs"
        if any(token in normalized for token in ("build", "ci", "workflow", "pipeline")):
            return "build"
        return "unknown"

    @staticmethod
    def _module_family(file_path: str) -> str | None:
        normalized = file_path.strip().replace("\\", "/")
        if not normalized:
            return None
        parts = [segment for segment in normalized.split("/") if segment]
        if len(parts) < 2:
            return parts[0] if parts else None
        return "/".join(parts[:2])

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
