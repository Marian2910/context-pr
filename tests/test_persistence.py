from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    RepositoryLockError,
    SCHEMA_VERSION,
    SonarIssueObservationRecord,
    SonarIssueRecord,
    SyncStateRecord,
)


def test_history_store_initializes_schema_and_version(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"

    store = HistoryStore(db_path)

    assert store.db_path == db_path
    assert db_path.is_file() is True
    assert store.get_schema_version() == SCHEMA_VERSION
    assert _table_exists(db_path, "repositories") is True
    assert _table_exists(db_path, "sync_state") is True
    assert _table_exists(db_path, "sonar_issues") is True
    assert _table_exists(db_path, "git_commits") is True
    assert _table_exists(db_path, "pull_requests") is True


def test_history_store_registers_repositories_and_reuses_existing_rows(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")

    first = store.ensure_repository("octo/example")
    second = store.ensure_repository("octo/example")
    third = store.ensure_repository("octo/another")

    assert first.repository_id == second.repository_id
    assert third.repository_id != first.repository_id
    assert [repository.repository_key for repository in store.list_repositories()] == [
        "octo/another",
        "octo/example",
    ]


def test_history_store_persists_repositories_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    HistoryStore(db_path).ensure_repository("octo/example")

    repositories = HistoryStore(db_path).list_repositories()

    assert len(repositories) == 1
    assert repositories[0].repository_key == "octo/example"


def test_history_store_upserts_sync_state_per_repository(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")

    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/example",
            source_name="sonar",
            cursor="cursor-1",
            updated_at="2026-05-16T10:00:00+00:00",
            metadata_json='{"page": 1}',
        )
    )
    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/example",
            source_name="sonar",
            cursor="cursor-2",
            updated_at="2026-05-16T11:00:00+00:00",
            metadata_json='{"page": 2}',
        )
    )
    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/another",
            source_name="sonar",
            cursor="other-cursor",
            updated_at="2026-05-16T12:00:00+00:00",
        )
    )

    first = store.get_sync_state("octo/example", "sonar")
    second = store.get_sync_state("octo/another", "sonar")

    assert first is not None
    assert first.cursor == "cursor-2"
    assert first.metadata_json == '{"page": 2}'
    assert second is not None
    assert second.cursor == "other-cursor"


def test_history_store_isolates_sonar_git_and_pr_records_by_repository(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")

    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="issue-1",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="MAJOR",
            component="src/app.py",
            message="Remove the unused parameter",
            status="OPEN",
            updated_at="2026-05-16T10:00:00+00:00",
        ),
    )
    store.record_sonar_issue_observation(
        "octo/example",
        SonarIssueObservationRecord(
            issue_key="issue-1",
            observed_at="2026-05-16T10:00:00+00:00",
            status="OPEN",
        ),
    )
    store.upsert_git_commit(
        "octo/example",
        GitCommitRecord(
            commit_sha="abc123",
            authored_at="2026-05-16T09:00:00+00:00",
            message="refactor: simplify handler",
            classification="refactor",
        ),
        touches=(
            GitFileTouchRecord(
                commit_sha="abc123",
                file_path="src/app.py",
                module_family="src",
            ),
        ),
    )
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=5,
            title="Refactor handler",
            state="merged",
            updated_at="2026-05-16T13:00:00+00:00",
        ),
        files=(PullRequestFileRecord(pr_number=5, file_path="src/app.py"),),
        review_comments=(
            PullRequestReviewCommentRecord(
                comment_id=7,
                pr_number=5,
                body="Please keep this branch explicit.",
                file_path="src/app.py",
                line=42,
                author_role="reviewer",
            ),
        ),
    )
    store.upsert_sonar_issue(
        "octo/another",
        SonarIssueRecord(
            issue_key="issue-2",
            rule="python:S1481",
            issue_type="CODE_SMELL",
            severity="MINOR",
            component="src/other.py",
            message="Remove the unused variable",
        ),
    )

    issues = store.list_sonar_issues("octo/example")
    observations = store.list_sonar_issue_observations("octo/example", "issue-1")
    touches = store.list_git_file_touches("octo/example")
    pull_request = store.get_pull_request("octo/example", 5)
    pr_files = store.list_pull_request_files("octo/example", 5)
    review_comments = store.list_pull_request_review_comments("octo/example", 5)

    assert [issue.issue_key for issue in issues] == ["issue-1"]
    assert [observation.issue_key for observation in observations] == ["issue-1"]
    assert [touch.file_path for touch in touches] == ["src/app.py"]
    assert pull_request is not None
    assert pull_request.title == "Refactor handler"
    assert [file_record.file_path for file_record in pr_files] == ["src/app.py"]
    assert [comment.comment_id for comment in review_comments] == [7]
    assert [issue.issue_key for issue in store.list_sonar_issues("octo/another")] == ["issue-2"]
    assert store.list_git_file_touches("octo/another") == []
    assert store.get_pull_request("octo/another", 5) is None


def test_history_store_replaces_git_touches_for_repeated_commit_upserts(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")

    store.upsert_git_commit(
        "octo/example",
        GitCommitRecord(
            commit_sha="abc123",
            authored_at="2026-05-16T09:00:00+00:00",
            message="refactor: simplify handler",
        ),
        touches=(GitFileTouchRecord(commit_sha="abc123", file_path="src/old.py"),),
    )
    store.upsert_git_commit(
        "octo/example",
        GitCommitRecord(
            commit_sha="abc123",
            authored_at="2026-05-16T09:00:00+00:00",
            message="refactor: simplify handler",
            classification="refactor",
        ),
        touches=(GitFileTouchRecord(commit_sha="abc123", file_path="src/new.py"),),
    )

    touches = store.list_git_file_touches("octo/example")

    assert [touch.file_path for touch in touches] == ["src/new.py"]


def test_repository_lock_rejects_parallel_nonblocking_lock_for_same_repo(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")

    with store.acquire_repository_lock("octo/example") as first_lock:
        assert first_lock.lock_file.is_file() is True
        with pytest.raises(RepositoryLockError):
            store.acquire_repository_lock("octo/example", blocking=False)

    with store.acquire_repository_lock("octo/example", blocking=False):
        pass


def _table_exists(db_path: Path, table_name: str) -> bool:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
    finally:
        connection.close()
    return row is not None
