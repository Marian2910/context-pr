import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from contextpr.config import Settings
from contextpr.integrations.sonarqube import (
    LOCAL_SONAR_SYNC_SOURCE,
    SonarProjectHistorySyncResult,
    SonarQubeClient,
)
from contextpr.persistence import HistoryStore, SyncStateRecord


def test_map_issue_preserves_text_range_end_line() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-1",
            "rule": "python:S3923",
            "severity": "MAJOR",
            "message": "Remove this if statement.",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
            "textRange": {
                "startLine": 154,
                "endLine": 157,
            },
        }
    )

    assert issue is not None
    assert issue.location.path == "src/app.py"
    assert issue.location.line == 154
    assert issue.location.end_line == 157


def test_map_issue_reads_location_from_flows_when_text_range_is_missing() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-2",
            "rule": "python:S1172",
            "severity": "MINOR",
            "message": "Remove unused parameter.",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
            "flows": [
                {
                    "locations": [
                        {
                            "textRange": {
                                "startLine": 40,
                                "endLine": 42,
                            }
                        }
                    ]
                }
            ],
        }
    )

    assert issue is not None
    assert issue.location.line == 40
    assert issue.location.end_line == 42


def test_map_issue_rejects_payload_without_component_path() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-3",
            "rule": "python:S1172",
            "severity": "MINOR",
            "message": "Remove unused parameter.",
            "type": "CODE_SMELL",
            "component": "src/app.py",
        }
    )

    assert issue is None


def test_map_issue_rejects_payload_with_missing_required_strings() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-4",
            "rule": "python:S1172",
            "severity": "MINOR",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
        }
    )

    assert issue is None


def test_sync_project_issue_history_persists_issues_and_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SonarQubeClient(
        Settings(
            sonar_token="sonar-token",
            sonar_project_key="contextpr",
        )
    )
    store = HistoryStore(tmp_path / "history.db")
    requested_pages: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    payloads = {
        "1": {
            "total": 2,
            "issues": [
                {
                    "key": "issue-1",
                    "rule": "python:S1172",
                    "severity": "MAJOR",
                    "message": "Remove the unused parameter.",
                    "type": "CODE_SMELL",
                    "component": "project:src/app.py",
                    "tags": ["unused"],
                    "status": "OPEN",
                    "creationDate": "2026-05-15T10:00:00+0000",
                    "updateDate": "2026-05-16T11:00:00+0000",
                    "textRange": {"startLine": 10, "endLine": 10},
                },
                {
                    "key": "issue-2",
                    "rule": "python:S1481",
                    "severity": "MINOR",
                    "message": "Remove the unused local variable.",
                    "type": "CODE_SMELL",
                    "component": "project:src/other.py",
                    "status": "CLOSED",
                    "resolution": "FIXED",
                    "creationDate": "2026-05-14T10:00:00+0000",
                    "updateDate": "2026-05-16T09:00:00+0000",
                    "textRange": {"startLine": 20, "endLine": 20},
                },
            ],
        }
    }

    def fake_urlopen(request: object, **_kwargs: object) -> FakeResponse:
        full_url = getattr(request, "full_url")
        page = parse_qs(urlparse(full_url).query)["p"][0]
        requested_pages.append(page)
        return FakeResponse(payloads[page])

    monkeypatch.setattr("contextpr.integrations.sonarqube.urlopen", fake_urlopen)

    result = client.sync_project_issue_history(
        store=store,
        repository_key="octo/example",
    )

    assert isinstance(result, SonarProjectHistorySyncResult)
    assert requested_pages == ["1"]
    assert result.issues_upserted == 2
    assert result.observations_recorded == 2
    assert result.latest_update == "2026-05-16T11:00:00+0000"
    assert [issue.issue_key for issue in store.list_sonar_issues("octo/example")] == [
        "issue-1",
        "issue-2",
    ]
    checkpoint = store.get_sync_state("octo/example", LOCAL_SONAR_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "2026-05-16T11:00:00+0000"


def test_sync_project_issue_history_stops_when_it_reaches_existing_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SonarQubeClient(
        Settings(
            sonar_token="sonar-token",
            sonar_project_key="contextpr",
        )
    )
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sync_state(
        SyncStateRecord(
            repository_key="octo/example",
            source_name=LOCAL_SONAR_SYNC_SOURCE,
            cursor="2026-05-16T11:00:00+0000",
            updated_at="2026-05-16T11:00:00+0000",
        )
    )
    requested_pages: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(request: object, **_kwargs: object) -> FakeResponse:
        full_url = getattr(request, "full_url")
        requested_pages.append(parse_qs(urlparse(full_url).query)["p"][0])
        return FakeResponse(
            {
                "total": 2,
                "issues": [
                    {
                        "key": "issue-new",
                        "rule": "python:S1172",
                        "severity": "MAJOR",
                        "message": "Remove the unused parameter.",
                        "type": "CODE_SMELL",
                        "component": "project:src/app.py",
                        "status": "OPEN",
                        "updateDate": "2026-05-16T12:00:00+0000",
                        "textRange": {"startLine": 10, "endLine": 10},
                    },
                    {
                        "key": "issue-old",
                        "rule": "python:S1481",
                        "severity": "MINOR",
                        "message": "Remove the unused local variable.",
                        "type": "CODE_SMELL",
                        "component": "project:src/other.py",
                        "status": "OPEN",
                        "updateDate": "2026-05-16T11:00:00+0000",
                        "textRange": {"startLine": 20, "endLine": 20},
                    },
                ],
            }
        )

    monkeypatch.setattr("contextpr.integrations.sonarqube.urlopen", fake_urlopen)

    result = client.sync_project_issue_history(
        store=store,
        repository_key="octo/example",
    )

    assert requested_pages == ["1"]
    assert result.issues_upserted == 1
    assert [issue.issue_key for issue in store.list_sonar_issues("octo/example")] == ["issue-new"]
    checkpoint = store.get_sync_state("octo/example", LOCAL_SONAR_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == "2026-05-16T12:00:00+0000"


def test_sync_project_issue_record_skips_observation_when_no_timestamp(tmp_path: Path) -> None:
    client = SonarQubeClient(
        Settings(
            sonar_token="sonar-token",
            sonar_project_key="contextpr",
        )
    )
    store = HistoryStore(tmp_path / "history.db")

    recorded = client._sync_project_issue_record(
        store=store,
        repository_key="octo/example",
        raw_issue={
            "key": "issue-no-dates",
            "rule": "python:S1172",
            "severity": "MAJOR",
            "message": "Remove the unused parameter.",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
            "status": "OPEN",
            "textRange": {"startLine": 10, "endLine": 10},
        },
        updated_at=None,
    )

    assert recorded == 0
    assert [issue.issue_key for issue in store.list_sonar_issues("octo/example")] == [
        "issue-no-dates"
    ]
