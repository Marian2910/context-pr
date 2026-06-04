from __future__ import annotations

import sqlite3

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


def repository_from_row(row: sqlite3.Row) -> RepositoryRecord:
    return RepositoryRecord(
        repository_id=int(row["repository_id"]),
        repository_key=str(row["repository_key"]),
        created_at=str(row["created_at"]),
    )


def sync_state_from_row(repository_key: str, row: sqlite3.Row) -> SyncStateRecord:
    return SyncStateRecord(
        repository_key=repository_key,
        source_name=str(row["source_name"]),
        cursor=row_value(row, "cursor"),
        updated_at=row_value(row, "updated_at"),
        metadata_json=row_value(row, "metadata_json"),
    )


def sonar_issue_from_row(row: sqlite3.Row) -> SonarIssueRecord:
    return SonarIssueRecord(
        issue_key=str(row["issue_key"]),
        rule=str(row["rule"]),
        issue_type=str(row["issue_type"]),
        severity=str(row["severity"]),
        component=str(row["component"]),
        message=str(row["message"]),
        tags_json=row_value(row, "tags_json"),
        clean_code_attribute=row_value(row, "clean_code_attribute"),
        clean_code_attribute_category=row_value(row, "clean_code_attribute_category"),
        status=row_value(row, "status"),
        resolution=row_value(row, "resolution"),
        created_at=row_value(row, "created_at"),
        updated_at=row_value(row, "updated_at"),
        branch=row_value(row, "branch"),
        line=row["line"],
        end_line=row["end_line"],
    )


def sonar_issue_observation_from_row(row: sqlite3.Row) -> SonarIssueObservationRecord:
    return SonarIssueObservationRecord(
        issue_key=str(row["issue_key"]),
        observed_at=str(row["observed_at"]),
        status=row_value(row, "status"),
        resolution=row_value(row, "resolution"),
        severity=row_value(row, "severity"),
        component=row_value(row, "component"),
        branch=row_value(row, "branch"),
        message=row_value(row, "message"),
    )


def git_commit_from_row(row: sqlite3.Row) -> GitCommitRecord:
    return GitCommitRecord(
        commit_sha=str(row["commit_sha"]),
        authored_at=str(row["authored_at"]),
        message=str(row["message"]),
        classification=str(row["classification"]),
    )


def git_file_touch_from_row(row: sqlite3.Row) -> GitFileTouchRecord:
    return GitFileTouchRecord(
        commit_sha=str(row["commit_sha"]),
        file_path=str(row["file_path"]),
        module_family=row_value(row, "module_family"),
    )


def pull_request_from_row(row: sqlite3.Row) -> PullRequestRecord:
    return PullRequestRecord(
        pr_number=int(row["pr_number"]),
        title=str(row["title"]),
        body=row_value(row, "body"),
        state=row_value(row, "state"),
        merged_at=row_value(row, "merged_at"),
        updated_at=row_value(row, "updated_at"),
    )


def pull_request_file_from_row(row: sqlite3.Row) -> PullRequestFileRecord:
    return PullRequestFileRecord(
        pr_number=int(row["pr_number"]),
        file_path=str(row["file_path"]),
    )


def pull_request_review_comment_from_row(
    row: sqlite3.Row,
) -> PullRequestReviewCommentRecord:
    return PullRequestReviewCommentRecord(
        comment_id=int(row["comment_id"]),
        pr_number=int(row["pr_number"]),
        body=str(row["body"]),
        file_path=row_value(row, "file_path"),
        line=row["line"],
        author_role=row_value(row, "author_role"),
        created_at=row_value(row, "created_at"),
        updated_at=row_value(row, "updated_at"),
    )


def row_value(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    return str(value)
