from __future__ import annotations

from collections.abc import Callable

from contextpr.persistence.records import (
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    RepositoryRecord,
)
from contextpr.persistence.repositories import (
    ConnectionFactory,
    executemany_if_rows,
    fetch_repository_row,
    fetch_repository_rows,
)
from contextpr.persistence.row_mappers import (
    pull_request_file_from_row,
    pull_request_from_row,
    pull_request_review_comment_from_row,
)


class PullRequestHistoryOperations:
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

    def upsert_pull_request(
        self,
        repository_key: str,
        record: PullRequestRecord,
        *,
        files: tuple[PullRequestFileRecord, ...] = (),
        review_comments: tuple[PullRequestReviewCommentRecord, ...] = (),
    ) -> None:
        repository = self._ensure_repository(repository_key)
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
            executemany_if_rows(
                connection,
                """
                INSERT INTO pull_request_files (
                    repository_id,
                    pr_number,
                    file_path
                )
                VALUES (?, ?, ?)
                """,
                (
                    (
                        repository.repository_id,
                        file_record.pr_number,
                        file_record.file_path,
                    )
                    for file_record in files
                ),
            )
            executemany_if_rows(
                connection,
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
                (
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
                ),
            )
            connection.commit()

    def get_pull_request(
        self,
        repository_key: str,
        pr_number: int,
    ) -> PullRequestRecord | None:
        row = fetch_repository_row(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT pr_number, title, body, state, merged_at, updated_at
            FROM pull_requests
            WHERE repository_id = ? AND pr_number = ?
            """,
            params=(pr_number,),
        )
        if row is None:
            return None
        return pull_request_from_row(row)

    def list_pull_requests(self, repository_key: str) -> list[PullRequestRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT pr_number, title, body, state, merged_at, updated_at
            FROM pull_requests
            WHERE repository_id = ?
            ORDER BY updated_at DESC, pr_number DESC
            """,
        )
        return [pull_request_from_row(row) for row in rows]

    def list_pull_request_files(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestFileRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT pr_number, file_path
            FROM pull_request_files
            WHERE repository_id = ? AND pr_number = ?
            ORDER BY file_path
            """,
            params=(pr_number,),
        )
        return [pull_request_file_from_row(row) for row in rows]

    def list_pull_request_review_comments(
        self,
        repository_key: str,
        pr_number: int,
    ) -> list[PullRequestReviewCommentRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT comment_id, pr_number, body, file_path, line,
                   author_role, created_at, updated_at
            FROM pull_request_review_comments
            WHERE repository_id = ? AND pr_number = ?
            ORDER BY comment_id
            """,
            params=(pr_number,),
        )
        return [pull_request_review_comment_from_row(row) for row in rows]

    def list_all_pull_request_review_comments(
        self,
        repository_key: str,
    ) -> list[PullRequestReviewCommentRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT comment_id, pr_number, body, file_path, line,
                   author_role, created_at, updated_at
            FROM pull_request_review_comments
            WHERE repository_id = ?
            ORDER BY updated_at DESC, comment_id DESC
            """,
        )
        return [pull_request_review_comment_from_row(row) for row in rows]
