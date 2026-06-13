from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from contextpr.persistence import (
    HistoryStore,
    PullRequestFileRecord,
    PullRequestReviewCommentRecord,
    SyncStateRecord,
)
from contextpr.services.review_comments import COMMENT_MARKER_PREFIX

from . import mapper
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

if TYPE_CHECKING:
    from . import GitHubClient


class GitHubRepositoryHistorySync:
    def __init__(self, client: GitHubClient) -> None:
        self._client = client

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
                payload = self._client._get_json_list(
                    f"/repos/{repository_key}/pulls?state=all&sort=updated&direction=desc&per_page={page_size}&page={page_number}"
                )
                pages_fetched += 1
                if not payload:
                    break

                page_result = self.sync_pull_request_page(
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
                            updated_at=utc_now(),
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

    def sync_pull_request_page(
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
            if not isinstance(item, dict):
                continue
            pull_requests_seen += 1
            updated_at = mapper.optional_string(item, "updated_at")
            if previous_cursor and updated_at and updated_at <= previous_cursor:
                should_stop = True
                continue
            if updated_at and (latest_update is None or updated_at > latest_update):
                latest_update = updated_at

            synced = self.sync_pull_request_record(store, repository_key, item)
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

    def sync_pull_request_record(
        self,
        store: HistoryStore,
        repository_key: str,
        item: dict[str, object],
    ) -> GitHubPullRequestSyncRecord | None:
        record = mapper.map_pull_request_record(item)
        if record is None:
            return None

        pull_request = self._client._pull_request_ref(repository_key, record.pr_number)
        files = tuple(
            PullRequestFileRecord(pr_number=record.pr_number, file_path=file_record.path)
            for file_record in self._client.get_pull_request_files(pull_request)
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
            for comment in self._client.list_existing_review_comments(pull_request)
            if COMMENT_MARKER_PREFIX not in comment.body
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


class GitHubCommitHistorySync:
    def __init__(self, client: GitHubClient) -> None:
        self._client = client

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
                payload = self._client._get_json_list(
                    f"/repos/{repository_key}/commits?per_page={page_size}&page={page_number}"
                )
                pages_fetched += 1
                if not payload:
                    break

                page_result = self.sync_commit_page(
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
                            updated_at=utc_now(),
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

    def sync_commit_page(
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
            if not isinstance(item, dict):
                continue
            commit_sha = mapper.optional_string(item, "sha")
            if commit_sha is None:
                continue
            commits_seen += 1
            if previous_cursor and commit_sha == previous_cursor:
                should_stop = True
                break

            synced = self.sync_commit_record(store, repository_key, commit_sha)
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

    def sync_commit_record(
        self,
        store: HistoryStore,
        repository_key: str,
        commit_sha: str,
    ) -> GitHubCommitSyncRecord | None:
        commit_payload = self._client._get_json_mapping(
            f"/repos/{repository_key}/commits/{commit_sha}"
        )
        mapped = mapper.map_commit_history(commit_payload)
        if mapped is None:
            return None

        commit_record, touches = mapped
        store.upsert_git_commit(repository_key, commit_record, touches=touches)
        return GitHubCommitSyncRecord(
            commit_sha=commit_record.commit_sha,
            authored_at=commit_record.authored_at,
            touches_recorded=len(touches),
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
