from __future__ import annotations

import contextlib
import fcntl
import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Self

SCHEMA_VERSION = 1

_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class HistoryStoreError(RuntimeError):
    """Raised when the local history store cannot be used safely."""


class RepositoryLockError(HistoryStoreError):
    """Raised when a repository lock cannot be acquired."""


class SchemaVersionError(HistoryStoreError):
    """Raised when the on-disk schema is newer than the current code expects."""


@dataclass(frozen=True, slots=True)
class RepositoryRecord:
    repository_id: int
    repository_key: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SyncStateRecord:
    repository_key: str
    source_name: str
    cursor: str | None = None
    updated_at: str | None = None
    metadata_json: str | None = None


@dataclass(frozen=True, slots=True)
class SonarIssueRecord:
    issue_key: str
    rule: str
    issue_type: str
    severity: str
    component: str
    message: str
    tags_json: str | None = None
    clean_code_attribute: str | None = None
    clean_code_attribute_category: str | None = None
    status: str | None = None
    resolution: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None


@dataclass(frozen=True, slots=True)
class SonarIssueObservationRecord:
    issue_key: str
    observed_at: str
    status: str | None = None
    resolution: str | None = None
    severity: str | None = None
    component: str | None = None
    branch: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class GitCommitRecord:
    commit_sha: str
    authored_at: str
    message: str
    classification: str = "unknown"


@dataclass(frozen=True, slots=True)
class GitFileTouchRecord:
    commit_sha: str
    file_path: str
    module_family: str | None = None


@dataclass(frozen=True, slots=True)
class PullRequestRecord:
    pr_number: int
    title: str
    body: str | None = None
    state: str | None = None
    merged_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class PullRequestFileRecord:
    pr_number: int
    file_path: str


@dataclass(frozen=True, slots=True)
class PullRequestReviewCommentRecord:
    comment_id: int
    pr_number: int
    body: str
    file_path: str | None = None
    line: int | None = None
    author_role: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class RepositoryLock:
    def __init__(
        self,
        *,
        repository_key: str,
        thread_lock: threading.Lock,
        lock_file: Path,
        handle: BinaryIO,
    ) -> None:
        self.repository_key = repository_key
        self._thread_lock = thread_lock
        self._lock_file = lock_file
        self._handle = handle
        self._released = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    @property
    def lock_file(self) -> Path:
        return self._lock_file

    def release(self) -> None:
        if self._released:
            return

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._thread_lock.release()
        self._released = True


class RepositoryLockManager:
    def __init__(self, lock_dir: Path) -> None:
        self._lock_dir = lock_dir.expanduser()

    def acquire(
        self,
        repository_key: str,
        *,
        blocking: bool = True,
        timeout_seconds: float | None = None,
    ) -> RepositoryLock:
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_dir / _repository_lock_filename(repository_key)
        thread_lock = _thread_lock_for(lock_file)
        if not _acquire_thread_lock(
            thread_lock,
            blocking=blocking,
            timeout_seconds=timeout_seconds,
        ):
            raise RepositoryLockError(
                f"Could not acquire in-process lock for repository {repository_key!r}."
            )

        handle = lock_file.open("a+b")
        try:
            _acquire_file_lock(
                handle,
                blocking=blocking,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            handle.close()
            thread_lock.release()
            raise

        return RepositoryLock(
            repository_key=repository_key,
            thread_lock=thread_lock,
            lock_file=lock_file,
            handle=handle,
        )


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser()
        self._lock_manager = RepositoryLockManager(self.db_path.parent / "locks")
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
            return _read_schema_version(connection)

    def ensure_repository(self, repository_key: str) -> RepositoryRecord:
        with self._connect() as connection:
            repository = self._get_repository(connection, repository_key)
            if repository is not None:
                return repository

            created_at = _utc_now()
            cursor = connection.execute(
                """
                INSERT INTO repositories (repository_key, created_at)
                VALUES (?, ?)
                """,
                (repository_key, created_at),
            )
            connection.commit()
            return RepositoryRecord(
                repository_id=int(cursor.lastrowid),
                repository_key=repository_key,
                created_at=created_at,
            )

    def get_repository(self, repository_key: str) -> RepositoryRecord | None:
        with self._connect() as connection:
            return self._get_repository(connection, repository_key)

    def list_repositories(self) -> list[RepositoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT repository_id, repository_key, created_at
                FROM repositories
                ORDER BY repository_key
                """
            ).fetchall()
        return [_repository_from_row(row) for row in rows]

    def upsert_sync_state(self, record: SyncStateRecord) -> None:
        repository = self.ensure_repository(record.repository_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state (
                    repository_id,
                    source_name,
                    cursor,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, source_name) DO UPDATE SET
                    cursor=excluded.cursor,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    repository.repository_id,
                    record.source_name,
                    record.cursor,
                    record.updated_at,
                    record.metadata_json,
                ),
            )
            connection.commit()

    def get_sync_state(
        self,
        repository_key: str,
        source_name: str,
    ) -> SyncStateRecord | None:
        repository = self.get_repository(repository_key)
        if repository is None:
            return None

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT source_name, cursor, updated_at, metadata_json
                FROM sync_state
                WHERE repository_id = ? AND source_name = ?
                """,
                (repository.repository_id, source_name),
            ).fetchone()
        if row is None:
            return None
        return SyncStateRecord(
            repository_key=repository_key,
            source_name=str(row["source_name"]),
            cursor=_row_value(row, "cursor"),
            updated_at=_row_value(row, "updated_at"),
            metadata_json=_row_value(row, "metadata_json"),
        )

    def upsert_sonar_issue(self, repository_key: str, record: SonarIssueRecord) -> None:
        repository = self.ensure_repository(repository_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sonar_issues (
                    repository_id,
                    issue_key,
                    rule,
                    issue_type,
                    severity,
                    component,
                    message,
                    tags_json,
                    clean_code_attribute,
                    clean_code_attribute_category,
                    status,
                    resolution,
                    created_at,
                    updated_at,
                    branch
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, issue_key) DO UPDATE SET
                    rule=excluded.rule,
                    issue_type=excluded.issue_type,
                    severity=excluded.severity,
                    component=excluded.component,
                    message=excluded.message,
                    tags_json=excluded.tags_json,
                    clean_code_attribute=excluded.clean_code_attribute,
                    clean_code_attribute_category=excluded.clean_code_attribute_category,
                    status=excluded.status,
                    resolution=excluded.resolution,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    branch=excluded.branch
                """,
                (
                    repository.repository_id,
                    record.issue_key,
                    record.rule,
                    record.issue_type,
                    record.severity,
                    record.component,
                    record.message,
                    record.tags_json,
                    record.clean_code_attribute,
                    record.clean_code_attribute_category,
                    record.status,
                    record.resolution,
                    record.created_at,
                    record.updated_at,
                    record.branch,
                ),
            )
            connection.commit()

    def list_sonar_issues(self, repository_key: str) -> list[SonarIssueRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT issue_key, rule, issue_type, severity, component, message,
                       tags_json, clean_code_attribute, clean_code_attribute_category,
                       status, resolution, created_at, updated_at, branch
                FROM sonar_issues
                WHERE repository_id = ?
                ORDER BY issue_key
                """,
                (repository.repository_id,),
            ).fetchall()
        return [
            SonarIssueRecord(
                issue_key=str(row["issue_key"]),
                rule=str(row["rule"]),
                issue_type=str(row["issue_type"]),
                severity=str(row["severity"]),
                component=str(row["component"]),
                message=str(row["message"]),
                tags_json=_row_value(row, "tags_json"),
                clean_code_attribute=_row_value(row, "clean_code_attribute"),
                clean_code_attribute_category=_row_value(row, "clean_code_attribute_category"),
                status=_row_value(row, "status"),
                resolution=_row_value(row, "resolution"),
                created_at=_row_value(row, "created_at"),
                updated_at=_row_value(row, "updated_at"),
                branch=_row_value(row, "branch"),
            )
            for row in rows
        ]

    def record_sonar_issue_observation(
        self,
        repository_key: str,
        record: SonarIssueObservationRecord,
    ) -> None:
        repository = self.ensure_repository(repository_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sonar_issue_observations (
                    repository_id,
                    issue_key,
                    observed_at,
                    status,
                    resolution,
                    severity,
                    component,
                    branch,
                    message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repository.repository_id,
                    record.issue_key,
                    record.observed_at,
                    record.status,
                    record.resolution,
                    record.severity,
                    record.component,
                    record.branch,
                    record.message,
                ),
            )
            connection.commit()

    def list_sonar_issue_observations(
        self,
        repository_key: str,
        issue_key: str,
    ) -> list[SonarIssueObservationRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT issue_key, observed_at, status, resolution, severity,
                       component, branch, message
                FROM sonar_issue_observations
                WHERE repository_id = ? AND issue_key = ?
                ORDER BY observed_at
                """,
                (repository.repository_id, issue_key),
            ).fetchall()
        return [
            SonarIssueObservationRecord(
                issue_key=str(row["issue_key"]),
                observed_at=str(row["observed_at"]),
                status=_row_value(row, "status"),
                resolution=_row_value(row, "resolution"),
                severity=_row_value(row, "severity"),
                component=_row_value(row, "component"),
                branch=_row_value(row, "branch"),
                message=_row_value(row, "message"),
            )
            for row in rows
        ]

    def upsert_git_commit(
        self,
        repository_key: str,
        record: GitCommitRecord,
        *,
        touches: tuple[GitFileTouchRecord, ...] = (),
    ) -> None:
        repository = self.ensure_repository(repository_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO git_commits (
                    repository_id,
                    commit_sha,
                    authored_at,
                    message,
                    classification
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, commit_sha) DO UPDATE SET
                    authored_at=excluded.authored_at,
                    message=excluded.message,
                    classification=excluded.classification
                """,
                (
                    repository.repository_id,
                    record.commit_sha,
                    record.authored_at,
                    record.message,
                    record.classification,
                ),
            )
            connection.execute(
                """
                DELETE FROM git_file_touches
                WHERE repository_id = ? AND commit_sha = ?
                """,
                (repository.repository_id, record.commit_sha),
            )
            connection.executemany(
                """
                INSERT INTO git_file_touches (
                    repository_id,
                    commit_sha,
                    file_path,
                    module_family
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        repository.repository_id,
                        touch.commit_sha,
                        touch.file_path,
                        touch.module_family,
                    )
                    for touch in touches
                ],
            )
            connection.commit()

    def list_git_commits(self, repository_key: str) -> list[GitCommitRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT commit_sha, authored_at, message, classification
                FROM git_commits
                WHERE repository_id = ?
                ORDER BY authored_at DESC, commit_sha DESC
                """,
                (repository.repository_id,),
            ).fetchall()
        return [
            GitCommitRecord(
                commit_sha=str(row["commit_sha"]),
                authored_at=str(row["authored_at"]),
                message=str(row["message"]),
                classification=str(row["classification"]),
            )
            for row in rows
        ]

    def list_git_file_touches(self, repository_key: str) -> list[GitFileTouchRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT commit_sha, file_path, module_family
                FROM git_file_touches
                WHERE repository_id = ?
                ORDER BY commit_sha, file_path
                """,
                (repository.repository_id,),
            ).fetchall()
        return [
            GitFileTouchRecord(
                commit_sha=str(row["commit_sha"]),
                file_path=str(row["file_path"]),
                module_family=_row_value(row, "module_family"),
            )
            for row in rows
        ]

    def upsert_pull_request(
        self,
        repository_key: str,
        record: PullRequestRecord,
        *,
        files: tuple[PullRequestFileRecord, ...] = (),
        review_comments: tuple[PullRequestReviewCommentRecord, ...] = (),
    ) -> None:
        repository = self.ensure_repository(repository_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pull_requests (
                    repository_id,
                    pr_number,
                    title,
                    body,
                    state,
                    merged_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, pr_number) DO UPDATE SET
                    title=excluded.title,
                    body=excluded.body,
                    state=excluded.state,
                    merged_at=excluded.merged_at,
                    updated_at=excluded.updated_at
                """,
                (
                    repository.repository_id,
                    record.pr_number,
                    record.title,
                    record.body,
                    record.state,
                    record.merged_at,
                    record.updated_at,
                ),
            )
            connection.execute(
                """
                DELETE FROM pull_request_files
                WHERE repository_id = ? AND pr_number = ?
                """,
                (repository.repository_id, record.pr_number),
            )
            connection.executemany(
                """
                INSERT INTO pull_request_files (
                    repository_id,
                    pr_number,
                    file_path
                )
                VALUES (?, ?, ?)
                """,
                [
                    (repository.repository_id, file_record.pr_number, file_record.file_path)
                    for file_record in files
                ],
            )
            connection.executemany(
                """
                INSERT INTO pull_request_review_comments (
                    repository_id,
                    comment_id,
                    pr_number,
                    body,
                    file_path,
                    line,
                    author_role,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, comment_id) DO UPDATE SET
                    pr_number=excluded.pr_number,
                    body=excluded.body,
                    file_path=excluded.file_path,
                    line=excluded.line,
                    author_role=excluded.author_role,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        repository.repository_id,
                        review_comment.comment_id,
                        review_comment.pr_number,
                        review_comment.body,
                        review_comment.file_path,
                        review_comment.line,
                        review_comment.author_role,
                        review_comment.created_at,
                        review_comment.updated_at,
                    )
                    for review_comment in review_comments
                ],
            )
            connection.commit()

    def get_pull_request(
        self,
        repository_key: str,
        pr_number: int,
    ) -> PullRequestRecord | None:
        repository = self.get_repository(repository_key)
        if repository is None:
            return None

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pr_number, title, body, state, merged_at, updated_at
                FROM pull_requests
                WHERE repository_id = ? AND pr_number = ?
                """,
                (repository.repository_id, pr_number),
            ).fetchone()
        if row is None:
            return None
        return PullRequestRecord(
            pr_number=int(row["pr_number"]),
            title=str(row["title"]),
            body=_row_value(row, "body"),
            state=_row_value(row, "state"),
            merged_at=_row_value(row, "merged_at"),
            updated_at=_row_value(row, "updated_at"),
        )

    def list_pull_requests(self, repository_key: str) -> list[PullRequestRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pr_number, title, body, state, merged_at, updated_at
                FROM pull_requests
                WHERE repository_id = ?
                ORDER BY updated_at DESC, pr_number DESC
                """,
                (repository.repository_id,),
            ).fetchall()
        return [
            PullRequestRecord(
                pr_number=int(row["pr_number"]),
                title=str(row["title"]),
                body=_row_value(row, "body"),
                state=_row_value(row, "state"),
                merged_at=_row_value(row, "merged_at"),
                updated_at=_row_value(row, "updated_at"),
            )
            for row in rows
        ]

    def list_pull_request_files(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestFileRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pr_number, file_path
                FROM pull_request_files
                WHERE repository_id = ? AND pr_number = ?
                ORDER BY file_path
                """,
                (repository.repository_id, pr_number),
            ).fetchall()
        return [
            PullRequestFileRecord(
                pr_number=int(row["pr_number"]),
                file_path=str(row["file_path"]),
            )
            for row in rows
        ]

    def list_pull_request_review_comments(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestReviewCommentRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT comment_id, pr_number, body, file_path, line,
                       author_role, created_at, updated_at
                FROM pull_request_review_comments
                WHERE repository_id = ? AND pr_number = ?
                ORDER BY comment_id
                """,
                (repository.repository_id, pr_number),
            ).fetchall()
        return [
            PullRequestReviewCommentRecord(
                comment_id=int(row["comment_id"]),
                pr_number=int(row["pr_number"]),
                body=str(row["body"]),
                file_path=_row_value(row, "file_path"),
                line=row["line"],
                author_role=_row_value(row, "author_role"),
                created_at=_row_value(row, "created_at"),
                updated_at=_row_value(row, "updated_at"),
            )
            for row in rows
        ]

    def list_all_pull_request_review_comments(
        self,
        repository_key: str,
    ) -> list[PullRequestReviewCommentRecord]:
        repository = self.get_repository(repository_key)
        if repository is None:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT comment_id, pr_number, body, file_path, line,
                       author_role, created_at, updated_at
                FROM pull_request_review_comments
                WHERE repository_id = ?
                ORDER BY updated_at DESC, comment_id DESC
                """,
                (repository.repository_id,),
            ).fetchall()
        return [
            PullRequestReviewCommentRecord(
                comment_id=int(row["comment_id"]),
                pr_number=int(row["pr_number"]),
                body=str(row["body"]),
                file_path=_row_value(row, "file_path"),
                line=row["line"],
                author_role=_row_value(row, "author_role"),
                created_at=_row_value(row, "created_at"),
                updated_at=_row_value(row, "updated_at"),
            )
            for row in rows
        ]

    @contextlib.contextmanager
    def _connect(self) -> sqlite3.Connection:
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
            self._apply_schema(connection)
            connection.commit()

    def _apply_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS repositories (
                repository_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                repository_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                cursor TEXT,
                updated_at TEXT,
                metadata_json TEXT,
                PRIMARY KEY (repository_id, source_name),
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sonar_issues (
                repository_id INTEGER NOT NULL,
                issue_key TEXT NOT NULL,
                rule TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT NOT NULL,
                tags_json TEXT,
                clean_code_attribute TEXT,
                clean_code_attribute_category TEXT,
                status TEXT,
                resolution TEXT,
                created_at TEXT,
                updated_at TEXT,
                branch TEXT,
                PRIMARY KEY (repository_id, issue_key),
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sonar_issue_observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                issue_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                status TEXT,
                resolution TEXT,
                severity TEXT,
                component TEXT,
                branch TEXT,
                message TEXT,
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS git_commits (
                repository_id INTEGER NOT NULL,
                commit_sha TEXT NOT NULL,
                authored_at TEXT NOT NULL,
                message TEXT NOT NULL,
                classification TEXT NOT NULL,
                PRIMARY KEY (repository_id, commit_sha),
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS git_file_touches (
                touch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                commit_sha TEXT NOT NULL,
                file_path TEXT NOT NULL,
                module_family TEXT,
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
                FOREIGN KEY (repository_id, commit_sha)
                    REFERENCES git_commits(repository_id, commit_sha) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pull_requests (
                repository_id INTEGER NOT NULL,
                pr_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                state TEXT,
                merged_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (repository_id, pr_number),
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pull_request_files (
                pull_request_file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                pr_number INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
                FOREIGN KEY (repository_id, pr_number)
                    REFERENCES pull_requests(repository_id, pr_number) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pull_request_review_comments (
                repository_id INTEGER NOT NULL,
                comment_id INTEGER NOT NULL,
                pr_number INTEGER NOT NULL,
                body TEXT NOT NULL,
                file_path TEXT,
                line INTEGER,
                author_role TEXT,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (repository_id, comment_id),
                FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
                FOREIGN KEY (repository_id, pr_number)
                    REFERENCES pull_requests(repository_id, pr_number) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sync_state_source
                ON sync_state(repository_id, source_name);
            CREATE INDEX IF NOT EXISTS idx_sonar_issue_rule
                ON sonar_issues(repository_id, rule);
            CREATE INDEX IF NOT EXISTS idx_sonar_issue_component
                ON sonar_issues(repository_id, component);
            CREATE INDEX IF NOT EXISTS idx_sonar_observation_issue
                ON sonar_issue_observations(repository_id, issue_key, observed_at);
            CREATE INDEX IF NOT EXISTS idx_git_touch_file
                ON git_file_touches(repository_id, file_path);
            CREATE INDEX IF NOT EXISTS idx_pull_request_file
                ON pull_request_files(repository_id, pr_number, file_path);
            CREATE INDEX IF NOT EXISTS idx_pull_request_comment_pr
                ON pull_request_review_comments(repository_id, pr_number);
            """
        )
        version = _read_schema_version(connection)
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"History store schema version {version} is newer than supported version "
                f"{SCHEMA_VERSION}."
            )
        connection.execute(
            """
            INSERT INTO schema_metadata (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )

    def _get_repository(
        self,
        connection: sqlite3.Connection,
        repository_key: str,
    ) -> RepositoryRecord | None:
        row = connection.execute(
            """
            SELECT repository_id, repository_key, created_at
            FROM repositories
            WHERE repository_key = ?
            """,
            (repository_key,),
        ).fetchone()
        if row is None:
            return None
        return _repository_from_row(row)


def _repository_from_row(row: sqlite3.Row) -> RepositoryRecord:
    return RepositoryRecord(
        repository_id=int(row["repository_id"]),
        repository_key=str(row["repository_key"]),
        created_at=str(row["created_at"]),
    )


def _read_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT value
        FROM schema_metadata
        WHERE key = 'schema_version'
        """
    ).fetchone()
    if row is None:
        return 0
    return int(row["value"])


def _row_value(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    return str(value)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _repository_lock_filename(repository_key: str) -> str:
    digest = hashlib.sha256(repository_key.encode("utf-8")).hexdigest()[:12]
    slug = repository_key.replace("/", "__").replace(":", "_")
    return f"{slug}-{digest}.lock"


def _thread_lock_for(lock_file: Path) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(lock_file)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[lock_file] = lock
        return lock


def _acquire_thread_lock(
    thread_lock: threading.Lock,
    *,
    blocking: bool,
    timeout_seconds: float | None,
) -> bool:
    if not blocking:
        return thread_lock.acquire(blocking=False)
    if timeout_seconds is None:
        thread_lock.acquire()
        return True
    return thread_lock.acquire(timeout=timeout_seconds)


def _acquire_file_lock(
    handle: BinaryIO,
    *,
    blocking: bool,
    timeout_seconds: float | None,
) -> None:
    if blocking and timeout_seconds is None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            if not blocking:
                raise RepositoryLockError("Repository lock is already held.") from exc
            if deadline is not None and time.monotonic() >= deadline:
                raise RepositoryLockError("Timed out while waiting for repository lock.") from exc
            time.sleep(0.05)
