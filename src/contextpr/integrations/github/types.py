from __future__ import annotations

from dataclasses import dataclass

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
