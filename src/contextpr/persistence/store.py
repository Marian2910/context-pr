from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from contextpr.persistence.git_history import GitHistoryOperations
from contextpr.persistence.locking import RepositoryLock, RepositoryLockManager
from contextpr.persistence.pr_history import PullRequestHistoryOperations
from contextpr.persistence.records import (
    GitCommitRecord,
    GitFileTouchRecord,
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    RepositoryRecord,
    SonarIssueObservationRecord,
    SonarIssueRecord,
    SyncStateRecord,
)
from contextpr.persistence.repositories import RepositoryOperations
from contextpr.persistence.schema import (
    SCHEMA_VERSION as SCHEMA_VERSION,
)
from contextpr.persistence.schema import (
    apply_schema,
    read_schema_version,
)
from contextpr.persistence.sonar_history import SonarHistoryOperations


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser()
        self._lock_manager = RepositoryLockManager(self.db_path.parent / "locks")
        self._repositories = RepositoryOperations(self._connect)
        self._sonar_history = SonarHistoryOperations(
            connect=self._connect,
            ensure_repository=self.ensure_repository,
            get_repository=self.get_repository,
        )
        self._git_history = GitHistoryOperations(
            connect=self._connect,
            ensure_repository=self.ensure_repository,
            get_repository=self.get_repository,
        )
        self._pr_history = PullRequestHistoryOperations(
            connect=self._connect,
            ensure_repository=self.ensure_repository,
            get_repository=self.get_repository,
        )
        self._initialize()

    def acquire_repository_lock(
        self,
        repository_key: str,
        *,
        blocking: bool = True,
        timeout_seconds: float | None = None,
    ) -> RepositoryLock:
        return self._lock_manager.acquire(
            repository_key,
            blocking=blocking,
            timeout_seconds=timeout_seconds,
        )

    def get_schema_version(self) -> int:
        with self._connect() as connection:
            return read_schema_version(connection)

    def ensure_repository(self, repository_key: str) -> RepositoryRecord:
        return self._repositories.ensure_repository(repository_key)

    def get_repository(self, repository_key: str) -> RepositoryRecord | None:
        return self._repositories.get_repository(repository_key)

    def list_repositories(self) -> list[RepositoryRecord]:
        return self._repositories.list_repositories()

    def upsert_sync_state(self, record: SyncStateRecord) -> None:
        self._repositories.upsert_sync_state(record)

    def get_sync_state(
        self,
        repository_key: str,
        source_name: str,
    ) -> SyncStateRecord | None:
        return self._repositories.get_sync_state(repository_key, source_name)

    def upsert_sonar_issue(self, repository_key: str, record: SonarIssueRecord) -> None:
        self._sonar_history.upsert_sonar_issue(repository_key, record)

    def list_sonar_issues(self, repository_key: str) -> list[SonarIssueRecord]:
        return self._sonar_history.list_sonar_issues(repository_key)

    def record_sonar_issue_observation(
        self,
        repository_key: str,
        record: SonarIssueObservationRecord,
    ) -> None:
        self._sonar_history.record_sonar_issue_observation(repository_key, record)

    def list_sonar_issue_observations(
        self,
        repository_key: str,
        issue_key: str,
    ) -> list[SonarIssueObservationRecord]:
        return self._sonar_history.list_sonar_issue_observations(
            repository_key,
            issue_key,
        )

    def upsert_git_commit(
        self,
        repository_key: str,
        record: GitCommitRecord,
        *,
        touches: tuple[GitFileTouchRecord, ...] = (),
    ) -> None:
        self._git_history.upsert_git_commit(repository_key, record, touches=touches)

    def list_git_commits(self, repository_key: str) -> list[GitCommitRecord]:
        return self._git_history.list_git_commits(repository_key)

    def list_git_file_touches(self, repository_key: str) -> list[GitFileTouchRecord]:
        return self._git_history.list_git_file_touches(repository_key)

    def upsert_pull_request(
        self,
        repository_key: str,
        record: PullRequestRecord,
        *,
        files: tuple[PullRequestFileRecord, ...] = (),
        review_comments: tuple[PullRequestReviewCommentRecord, ...] = (),
    ) -> None:
        self._pr_history.upsert_pull_request(
            repository_key,
            record,
            files=files,
            review_comments=review_comments,
        )

    def get_pull_request(
        self,
        repository_key: str,
        pr_number: int,
    ) -> PullRequestRecord | None:
        return self._pr_history.get_pull_request(repository_key, pr_number)

    def list_pull_requests(self, repository_key: str) -> list[PullRequestRecord]:
        return self._pr_history.list_pull_requests(repository_key)

    def list_pull_request_files(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestFileRecord]:
        return self._pr_history.list_pull_request_files(repository_key, pr_number)

    def list_pull_request_review_comments(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestReviewCommentRecord]:
        return self._pr_history.list_pull_request_review_comments(
            repository_key,
            pr_number,
        )

    def list_all_pull_request_review_comments(
        self,
        repository_key: str,
    ) -> list[PullRequestReviewCommentRecord]:
        return self._pr_history.list_all_pull_request_review_comments(repository_key)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            apply_schema(connection)
            connection.commit()
