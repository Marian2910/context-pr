from __future__ import annotations

from collections.abc import Callable

from contextpr.persistence.records import (
    RepositoryRecord,
    SonarIssueObservationRecord,
    SonarIssueRecord,
)
from contextpr.persistence.repositories import (
    ConnectionFactory,
    fetch_repository_rows,
)
from contextpr.persistence.row_mappers import (
    sonar_issue_from_row,
    sonar_issue_observation_from_row,
)


class SonarHistoryOperations:
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

    def upsert_sonar_issue(self, repository_key: str, record: SonarIssueRecord) -> None:
        repository = self._ensure_repository(repository_key)
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
                    branch,
                    line,
                    end_line
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    branch=excluded.branch,
                    line=excluded.line,
                    end_line=excluded.end_line
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
                    record.line,
                    record.end_line,
                ),
            )
            connection.commit()

    def list_sonar_issues(self, repository_key: str) -> list[SonarIssueRecord]:
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT issue_key, rule, issue_type, severity, component, message,
                   tags_json, clean_code_attribute, clean_code_attribute_category,
                   status, resolution, created_at, updated_at, branch,
                   line, end_line
            FROM sonar_issues
            WHERE repository_id = ?
            ORDER BY issue_key
            """,
        )
        return [sonar_issue_from_row(row) for row in rows]

    def record_sonar_issue_observation(
        self,
        repository_key: str,
        record: SonarIssueObservationRecord,
    ) -> None:
        repository = self._ensure_repository(repository_key)
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
        rows = fetch_repository_rows(
            connect=self._connect,
            get_repository=self._get_repository,
            repository_key=repository_key,
            query="""
            SELECT issue_key, observed_at, status, resolution, severity,
                   component, branch, message
            FROM sonar_issue_observations
            WHERE repository_id = ? AND issue_key = ?
            ORDER BY observed_at
            """,
            params=(issue_key,),
        )
        return [sonar_issue_observation_from_row(row) for row in rows]
