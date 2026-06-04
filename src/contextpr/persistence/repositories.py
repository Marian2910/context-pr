from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from contextpr.persistence.records import RepositoryRecord, SyncStateRecord
from contextpr.persistence.row_mappers import repository_from_row, sync_state_from_row

ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


class RepositoryOperations:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def ensure_repository(self, repository_key: str) -> RepositoryRecord:
        with self._connect() as connection:
            repository = self.get_repository_with_connection(connection, repository_key)
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
            assert cursor.lastrowid is not None
            return RepositoryRecord(
                repository_id=int(cursor.lastrowid),
                repository_key=repository_key,
                created_at=created_at,
            )

    def get_repository(self, repository_key: str) -> RepositoryRecord | None:
        with self._connect() as connection:
            return self.get_repository_with_connection(connection, repository_key)

    def get_repository_with_connection(
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
        return repository_from_row(row)

    def list_repositories(self) -> list[RepositoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT repository_id, repository_key, created_at
                FROM repositories
                ORDER BY repository_key
                """
            ).fetchall()
        return [repository_from_row(row) for row in rows]

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
        row = fetch_repository_row(
            connect=self._connect,
            get_repository=self.get_repository,
            repository_key=repository_key,
            query="""
            SELECT source_name, cursor, updated_at, metadata_json
            FROM sync_state
            WHERE repository_id = ? AND source_name = ?
            """,
            params=(source_name,),
        )
        if row is None:
            return None
        return sync_state_from_row(repository_key, row)


def fetch_repository_row(
    *,
    connect: ConnectionFactory,
    get_repository: Callable[[str], RepositoryRecord | None],
    repository_key: str,
    query: str,
    params: tuple[object, ...] = (),
) -> sqlite3.Row | None:
    rows = fetch_repository_rows(
        connect=connect,
        get_repository=get_repository,
        repository_key=repository_key,
        query=query,
        params=params,
    )
    return rows[0] if rows else None


def fetch_repository_rows(
    *,
    connect: ConnectionFactory,
    get_repository: Callable[[str], RepositoryRecord | None],
    repository_key: str,
    query: str,
    params: tuple[object, ...] = (),
) -> list[sqlite3.Row]:
    repository = get_repository(repository_key)
    if repository is None:
        return []

    with connect() as connection:
        rows = connection.execute(
            query,
            (repository.repository_id, *params),
        ).fetchall()
    return list(rows)


def executemany_if_rows(
    connection: sqlite3.Connection,
    query: str,
    rows: Iterator[tuple[object, ...]],
) -> None:
    buffered_rows = list(rows)
    if not buffered_rows:
        return
    connection.executemany(query, buffered_rows)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()
