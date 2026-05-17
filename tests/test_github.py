from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from urllib.request import Request

import pytest

from contextpr.config import Settings
from contextpr.integrations.github import (
    LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
    LOCAL_GITHUB_SYNC_SOURCE,
    GitHubCommitHistorySyncResult,
    GitHubClient,
    GitHubHistorySyncResult,
)
from contextpr.models import GitHubReviewComment, PullRequestRef
from contextpr.persistence import HistoryStore, SyncStateRecord


class FakeResponse:

    def __init__(self, payload: object | None = None) -> None:
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_review_comment_payload_includes_multiline_range() -> None:
    payload = GitHubClient._review_comment_payload(
        GitHubReviewComment(
            path="src/app.py",
            start_line=154,
            line=157,
            start_side="RIGHT",
            side="RIGHT",
            body="Review body",
        )
    )

    assert payload == {
        "path": "src/app.py",
        "start_line": 154,
        "line": 157,
        "start_side": "RIGHT",
        "side": "RIGHT",
        "body": "Review body",
    }


def test_review_comment_payload_omits_range_for_single_line_comment() -> None:
    payload = GitHubClient._review_comment_payload(
        GitHubReviewComment(
            path="src/app.py",
            line=155,
            body="Review body",
        )
    )

    assert payload == {
        "path": "src/app.py",
        "line": 155,
        "side": "RIGHT",
        "body": "Review body",
    }


def test_get_pull_request_files_maps_valid_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "contextpr.integrations.github.urlopen",
        lambda _request: FakeResponse(
            [
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n+new\n",
                },
                {"filename": 123, "status": "modified"},
            ]
        ),
    )

    files = _client().get_pull_request_files(PullRequestRef("octo/example", 1))

    assert len(files) == 1
    assert files[0].path == "src/app.py"
    assert files[0].patch == "@@ -1 +1 @@\n+new\n"


def test_list_existing_review_comments_maps_valid_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "contextpr.integrations.github.urlopen",
        lambda _request: FakeResponse(
            [
                {
                    "id": 10,
                    "path": "src/app.py",
                    "line": 7,
                    "body": "Comment body",
                    "user": {"login": "github-actions[bot]"},
                },
                {"id": "invalid"},
            ]
        ),
    )

    comments = _client().list_existing_review_comments(PullRequestRef("octo/example", 1))

    assert len(comments) == 1
    assert comments[0].comment_id == 10
    assert comments[0].author_login == "github-actions[bot]"


def test_create_review_sends_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Request) -> FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(cast(bytes, request.data or b"{}").decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("contextpr.integrations.github.urlopen", fake_urlopen)

    _client().create_review(
        pull_request=PullRequestRef("octo/example", 3),
        comments=[
            GitHubReviewComment(
                path="src/app.py",
                line=12,
                body="Body",
            )
        ],
    )

    assert captured["url"].endswith("/repos/octo/example/pulls/3/reviews")
    assert captured["method"] == "POST"
    assert captured["payload"]["event"] == "COMMENT"
    assert captured["payload"]["comments"][0]["path"] == "src/app.py"


def test_delete_review_comment_sends_delete_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: Request) -> FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return FakeResponse()

    monkeypatch.setattr("contextpr.integrations.github.urlopen", fake_urlopen)

    _client().delete_review_comment(42)

    assert captured["url"].endswith("/repos/octo/example/pulls/comments/42")
    assert captured["method"] == "DELETE"


def test_sync_repository_history_persists_pull_requests_files_and_review_comments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    client = _client()
    calls: list[str] = []

    def fake_get_json_list(path: str) -> list[object]:
        calls.append(path)
        if path.startswith("/repos/octo/example/pulls?"):
            return [
                {
                    "number": 7,
                    "title": "Refactor handler",
                    "body": "Cleanup with behavior review",
                    "state": "closed",
                    "merged_at": "2026-05-16T09:00:00Z",
                    "updated_at": "2026-05-16T10:00:00Z",
                }
            ]
        if path == "/repos/octo/example/pulls/7/files":
            return [
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n+new\n",
                }
            ]
        if path == "/repos/octo/example/pulls/7/comments":
            return [
                {
                    "id": 10,
                    "path": "src/app.py",
                    "line": 7,
                    "body": "Please confirm this is behavior-safe.",
                    "user": {"login": "reviewer-1"},
                }
            ]
        return []

    monkeypatch.setattr(client, "_get_json_list", fake_get_json_list)

    result = client.sync_repository_history(
        store=store,
        repository_key="octo/example",
    )

    assert isinstance(result, GitHubHistorySyncResult)
    assert result.pull_requests_upserted == 1
    assert result.files_recorded == 1
    assert result.review_comments_recorded == 1
    assert store.get_pull_request("octo/example", 7) is not None
    assert [file.file_path for file in store.list_pull_request_files("octo/example", 7)] == [
        "src/app.py"
    ]
    assert [
        comment.comment_id
        for comment in store.list_pull_request_review_comments("octo/example", 7)
    ] == [10]
    checkpoint = store.get_sync_state("octo/example", LOCAL_GITHUB_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "2026-05-16T10:00:00Z"


def test_sync_repository_history_stops_when_it_reaches_existing_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/example",
            source_name=LOCAL_GITHUB_SYNC_SOURCE,
            cursor="2026-05-16T10:00:00Z",
            updated_at="2026-05-16T10:00:00Z",
        )
    )
    client = _client()

    def fake_get_json_list(path: str) -> list[object]:
        if path.startswith("/repos/octo/example/pulls?"):
            return [
                {
                    "number": 8,
                    "title": "New cleanup",
                    "updated_at": "2026-05-16T10:30:00Z",
                },
                {
                    "number": 7,
                    "title": "Old cleanup",
                    "updated_at": "2026-05-16T10:00:00Z",
                },
            ]
        if path == "/repos/octo/example/pulls/8/files":
            return [{"filename": "src/app.py", "status": "modified"}]
        if path == "/repos/octo/example/pulls/8/comments":
            return []
        return []

    monkeypatch.setattr(client, "_get_json_list", fake_get_json_list)

    result = client.sync_repository_history(
        store=store,
        repository_key="octo/example",
    )

    assert result.pull_requests_upserted == 1
    assert [pull_request.pr_number for pull_request in store.list_pull_requests("octo/example")] == [8]
    checkpoint = store.get_sync_state("octo/example", LOCAL_GITHUB_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "2026-05-16T10:30:00Z"


def test_sync_commit_history_persists_commits_touches_and_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    client = _client()

    def fake_get_json(path: str) -> object:
        if path.startswith("/repos/octo/example/commits?"):
            return [
                {"sha": "sha-2"},
                {"sha": "sha-1"},
            ]
        if path == "/repos/octo/example/commits/sha-2":
            return {
                "sha": "sha-2",
                "commit": {
                    "message": "fix: patch behavior",
                    "author": {"date": "2026-05-16T11:00:00Z"},
                },
                "files": [{"filename": "src/app.py"}],
            }
        if path == "/repos/octo/example/commits/sha-1":
            return {
                "sha": "sha-1",
                "commit": {
                    "message": "refactor: simplify handler",
                    "author": {"date": "2026-05-16T10:00:00Z"},
                },
                "files": [{"filename": "src/other.py"}],
            }
        return {}

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    result = client.sync_commit_history(store=store, repository_key="octo/example")

    assert isinstance(result, GitHubCommitHistorySyncResult)
    assert result.commits_upserted == 2
    assert result.touches_recorded == 2
    assert result.latest_commit_sha == "sha-2"
    assert [commit.commit_sha for commit in store.list_git_commits("octo/example")] == ["sha-2", "sha-1"]
    assert [touch.file_path for touch in store.list_git_file_touches("octo/example")] == [
        "src/other.py",
        "src/app.py",
    ]
    checkpoint = store.get_sync_state("octo/example", LOCAL_GITHUB_COMMIT_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "sha-2"


def test_sync_commit_history_stops_when_it_reaches_existing_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/example",
            source_name=LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
            cursor="sha-1",
            updated_at="2026-05-16T10:00:00Z",
        )
    )
    client = _client()

    def fake_get_json(path: str) -> object:
        if path.startswith("/repos/octo/example/commits?"):
            return [
                {"sha": "sha-2"},
                {"sha": "sha-1"},
            ]
        if path == "/repos/octo/example/commits/sha-2":
            return {
                "sha": "sha-2",
                "commit": {
                    "message": "fix: patch behavior",
                    "author": {"date": "2026-05-16T11:00:00Z"},
                },
                "files": [{"filename": "src/app.py"}],
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    result = client.sync_commit_history(store=store, repository_key="octo/example")

    assert result.commits_upserted == 1
    assert [commit.commit_sha for commit in store.list_git_commits("octo/example")] == ["sha-2"]
    checkpoint = store.get_sync_state("octo/example", LOCAL_GITHUB_COMMIT_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "sha-2"


def _client() -> GitHubClient:
    return GitHubClient(
        Settings(
            github_token="workflow-token",
            github_repository="octo/example",
        )
    )
