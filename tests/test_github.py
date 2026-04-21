from __future__ import annotations

import json
from typing import Any, cast
from urllib.request import Request

import pytest

from contextpr.config import Settings
from contextpr.integrations.github import GitHubClient
from contextpr.models import GitHubReviewComment, PullRequestRef


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


def _client() -> GitHubClient:
    return GitHubClient(
        Settings(
            github_token="workflow-token",
            github_repository="octo/example",
        )
    )
