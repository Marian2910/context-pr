from __future__ import annotations

from collections.abc import Callable

from contextpr.persistence.records import (
    GitCommitRecord,
    GitFileTouchRecord,
    RepositoryRecord,
)
from contextpr.persistence.repositories import (
    ConnectionFactory,
    executemany_if_rows,
    fetch_repository_rows,
)
from contextpr.persistence.row_mappers import git_commit_from_row, git_file_touch_from_row


class GitHistoryOperations:
    def __init__(
        self,
        *,
        connect: ConnectionFactory,
        ensure_repository: Callable[[str], RepositoryRecord],
        get_repository: Callable[[str], RepositoryRecord | None],
    ) -> None:
        self._connect = connect
        self._ensure_repository = ensure_repository
        self._get_repository = get_repository

    def upsert_git_commit(
        self,
        repository_key: str,
        record: GitCommitRecord,
        *,
        touches: tuple[GitFileTouchRecord, ...] = (),
    ) -> None:
        repository = self._ensure_repository(repository_key)
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
            executemany_if_rows(
                connection,
                """
                INSERT INTO git_file_touches (
                    repository_id,
                    commit_sha,
                    file_path,
                    module_family
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        repository.repository_id,
                        touch.commit_sha,
                        touch.file_path,
                        touch.module_family,
                    )
                    for touch in touches
                ),
            )
            connection.commit()

    def list_git_commits(self, repository_key: str) -> list[GitCommitRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT commit_sha, authored_at, message, classification
            FROM git_commits
            WHERE repository_id = ?
            ORDER BY authored_at DESC, commit_sha DESC
            """,
        )
        return [git_commit_from_row(row) for row in rows]

    def list_git_file_touches(self, repository_key: str) -> list[GitFileTouchRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT commit_sha, file_path, module_family
            FROM git_file_touches
            WHERE repository_id = ?
            ORDER BY commit_sha, file_path
            """,
        )
        return [git_file_touch_from_row(row) for row in rows]
