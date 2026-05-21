from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from contextpr.config import Settings
from contextpr.models import IssueLocation, SonarIssue
from contextpr.persistence import (
    HistoryStore,
    SonarIssueObservationRecord,
    SonarIssueRecord,
    SyncStateRecord,
)

LOCAL_SONAR_SYNC_SOURCE = "local_sonar_project_issues"
PROJECT_HISTORY_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class SonarProjectHistorySyncResult:
    repository_key: str
    pages_fetched: int
    issues_seen: int
    issues_upserted: int
    observations_recorded: int
    latest_update: str | None


@dataclass(frozen=True, slots=True)
class SonarProjectHistoryPageResult:
    should_stop: bool
    issues_seen: int
    issues_upserted: int
    observations_recorded: int
    latest_update: str | None


class SonarQubeClient:

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return self._settings.sonar_enabled

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
        self._settings.require("sonar_token", "sonar_project_key")

        request = self._build_issues_request(pull_request_number)
        payload = self._execute_request(request)

        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            return []

        return [
            issue
            for raw_issue in issues
            if (issue := self._map_issue(raw_issue)) is not None
        ]

    def sync_project_issue_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int = PROJECT_HISTORY_PAGE_SIZE,
    ) -> SonarProjectHistorySyncResult:
        self._settings.require("sonar_token", "sonar_project_key")
        with store.acquire_repository_lock(repository_key):
            previous_state = store.get_sync_state(repository_key, LOCAL_SONAR_SYNC_SOURCE)
            previous_cursor = previous_state.cursor if previous_state is not None else None
            latest_update = previous_cursor
            page_number = 1
            pages_fetched = 0
            issues_seen = 0
            issues_upserted = 0
            observations_recorded = 0

            for resolved_filter in ("false", "true"):
                page_number = 1
                while True:
                    payload = self._execute_request(
                        self._build_project_history_request(
                            page_number,
                            page_size,
                            resolved=resolved_filter,
                        )
                    )
                    pages_fetched += 1
                    raw_issues = payload.get("issues", [])
                    total = payload.get("total", 0)
                    if not isinstance(raw_issues, list):
                        break

                    page_result = self._sync_project_history_page(
                        store=store,
                        repository_key=repository_key,
                        raw_issues=raw_issues,
                        previous_cursor=previous_cursor,
                        latest_update=latest_update,
                    )
                    issues_seen += page_result.issues_seen
                    issues_upserted += page_result.issues_upserted
                    observations_recorded += page_result.observations_recorded
                    latest_update = page_result.latest_update

                    if latest_update is not None:
                        store.upsert_sync_state(
                            SyncStateRecord(
                                repository_key=repository_key,
                                source_name=LOCAL_SONAR_SYNC_SOURCE,
                                cursor=latest_update,
                                updated_at=latest_update,
                            )
                        )

                    if page_result.should_stop:
                        break
                    if not isinstance(total, int) or page_number * page_size >= total:
                        break
                    page_number += 1

            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=pages_fetched,
                issues_seen=issues_seen,
                issues_upserted=issues_upserted,
                observations_recorded=observations_recorded,
                latest_update=latest_update,
            )

    def _sync_project_history_page(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        raw_issues: list[object],
        previous_cursor: str | None,
        latest_update: str | None,
    ) -> SonarProjectHistoryPageResult:
        should_stop = False
        issues_seen = 0
        issues_upserted = 0
        observations_recorded = 0

        for raw_issue in raw_issues:
            if not isinstance(raw_issue, Mapping):
                continue
            issues_seen += 1
            updated_at = self._optional_string(raw_issue, "updateDate")
            if previous_cursor and updated_at and updated_at <= previous_cursor:
                should_stop = True
                continue
            if updated_at and (latest_update is None or updated_at > latest_update):
                latest_update = updated_at

            synced = self._sync_project_issue_record(
                store=store,
                repository_key=repository_key,
                raw_issue=raw_issue,
                updated_at=updated_at,
            )
            if synced is None:
                continue
            issues_upserted += 1
            observations_recorded += synced

        return SonarProjectHistoryPageResult(
            should_stop=should_stop,
            issues_seen=issues_seen,
            issues_upserted=issues_upserted,
            observations_recorded=observations_recorded,
            latest_update=latest_update,
        )

    def _sync_project_issue_record(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        raw_issue: Mapping[str, object],
        updated_at: str | None,
    ) -> int | None:
        if (record := self._map_issue_record(raw_issue)) is None:
            return None

        store.upsert_sonar_issue(repository_key, record)
        observed_at = updated_at or record.created_at
        if observed_at is None:
            return 0

        store.record_sonar_issue_observation(
            repository_key,
            SonarIssueObservationRecord(
                issue_key=record.issue_key,
                observed_at=observed_at,
                status=record.status,
                resolution=record.resolution,
                severity=record.severity,
                component=record.component,
                branch=record.branch,
                message=record.message,
            ),
        )
        return 1

    def _build_issues_request(self, pull_request_number: int) -> Request:
        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "pullRequest": str(pull_request_number),
                "resolved": "false",
            }
        )

        return Request(
            url=f"{self._api_url('/api/issues/search')}?{params}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._basic_auth_token()}",
            },
        )

    def _build_project_history_request(
        self,
        page_number: int,
        page_size: int,
        *,
        resolved: str,
    ) -> Request:
        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "ps": str(page_size),
                "p": str(page_number),
                "s": "UPDATE_DATE",
                "asc": "false",
                "resolved": resolved,
            }
        )

        return Request(
            url=f"{self._api_url('/api/issues/search')}?{params}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._basic_auth_token()}",
            },
        )

    @staticmethod
    def _execute_request(request: Request) -> Mapping[str, object]:
        with urlopen(request) as response:
            return cast(Mapping[str, object], json.load(response))

    def _api_url(self, path: str) -> str:
        base_url = self._settings.sonar_host_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def _basic_auth_token(self) -> str:
        token = self._settings.sonar_token or ""
        return base64.b64encode(f"{token}:".encode()).decode("ascii")

    @staticmethod
    def _map_issue(payload: Mapping[str, object]) -> SonarIssue | None:
        component = payload.get("component")
        if not isinstance(component, str) or ":" not in component:
            return None

        fields = SonarQubeClient._extract_issue_fields(payload)
        if fields is None:
            return None

        path = component.split(":", maxsplit=1)[1]
        issue_key, rule, severity, message, line, end_line, issue_type = fields

        return SonarIssue(
            key=issue_key,
            rule=rule,
            severity=severity,
            message=message,
            location=IssueLocation(path=path, line=line, end_line=end_line),
            issue_type=issue_type,
            tags=SonarQubeClient._extract_tags(payload),
            clean_code_attribute=SonarQubeClient._extract_string(payload, "cleanCodeAttribute"),
            clean_code_attribute_category=SonarQubeClient._extract_string(
                payload,
                "cleanCodeAttributeCategory",
            ),
            effort=SonarQubeClient._optional_string(payload, "effort")
            or SonarQubeClient._optional_string(payload, "debt"),
        )

    @staticmethod
    def _map_issue_record(payload: Mapping[str, object]) -> SonarIssueRecord | None:
        issue = SonarQubeClient._map_issue(payload)
        if issue is None:
            return None

        return SonarIssueRecord(
            issue_key=issue.key,
            rule=issue.rule,
            issue_type=issue.issue_type,
            severity=issue.severity,
            component=issue.location.path,
            message=issue.message,
            tags_json=json.dumps(list(issue.tags)) if issue.tags else None,
            clean_code_attribute=issue.clean_code_attribute or None,
            clean_code_attribute_category=issue.clean_code_attribute_category or None,
            status=SonarQubeClient._optional_string(payload, "status"),
            resolution=SonarQubeClient._optional_string(payload, "resolution"),
            created_at=SonarQubeClient._optional_string(payload, "creationDate"),
            updated_at=SonarQubeClient._optional_string(payload, "updateDate"),
            branch=SonarQubeClient._optional_string(payload, "branch"),
            line=issue.location.line,
            end_line=issue.location.end_line,
        )

    @staticmethod
    def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _extract_issue_fields(
        payload: Mapping[str, object],
    ) -> tuple[str, str, str, str, int | None, int | None, str] | None:
        issue_key = payload.get("key")
        rule = payload.get("rule")
        severity = payload.get("severity")
        message = payload.get("message")
        issue_type = payload.get("type")

        if not all(
            isinstance(value, str)
            for value in (issue_key, rule, severity, message, issue_type)
        ):
            return None

        return (
            cast(str, issue_key),
            cast(str, rule),
            cast(str, severity),
            cast(str, message),
            SonarQubeClient._extract_start_line(payload),
            SonarQubeClient._extract_end_line(payload),
            cast(str, issue_type),
        )

    @staticmethod
    def _extract_tags(payload: Mapping[str, object]) -> tuple[str, ...]:
        tags = payload.get("tags")
        if not isinstance(tags, list):
            return ()

        return tuple(tag for tag in tags if isinstance(tag, str))

    @staticmethod
    def _extract_string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if isinstance(value, str):
            return value

        return ""

    @staticmethod
    def _extract_start_line(payload: Mapping[str, object]) -> int | None:
        return (
            SonarQubeClient._line_from_text_range(payload)
            or SonarQubeClient._line_from_flows(payload)
        )

    @staticmethod
    def _extract_end_line(payload: Mapping[str, object]) -> int | None:
        return (
            SonarQubeClient._end_line_from_text_range(payload)
            or SonarQubeClient._end_line_from_flows(payload)
        )

    @staticmethod
    def _line_from_text_range(payload: Mapping[str, object]) -> int | None:
        return SonarQubeClient._get_start_line(payload.get("textRange"))

    @staticmethod
    def _end_line_from_text_range(payload: Mapping[str, object]) -> int | None:
        return SonarQubeClient._get_end_line(payload.get("textRange"))

    @staticmethod
    def _line_from_flows(payload: Mapping[str, object]) -> int | None:
        flows = payload.get("flows")
        if not isinstance(flows, list):
            return None

        for flow in flows:
            line = SonarQubeClient._line_from_flow(flow)
            if line is not None:
                return line

        return None

    @staticmethod
    def _end_line_from_flows(payload: Mapping[str, object]) -> int | None:
        flows = payload.get("flows")
        if not isinstance(flows, list):
            return None

        for flow in flows:
            line = SonarQubeClient._end_line_from_flow(flow)
            if line is not None:
                return line

        return None

    @staticmethod
    def _line_from_flow(flow: object) -> int | None:
        if not isinstance(flow, Mapping):
            return None

        locations = flow.get("locations")
        if not isinstance(locations, list):
            return None

        for location in locations:
            line = SonarQubeClient._line_from_location(location)
            if line is not None:
                return line

        return None

    @staticmethod
    def _end_line_from_flow(flow: object) -> int | None:
        if not isinstance(flow, Mapping):
            return None

        locations = flow.get("locations")
        if not isinstance(locations, list):
            return None

        for location in locations:
            line = SonarQubeClient._end_line_from_location(location)
            if line is not None:
                return line

        return None

    @staticmethod
    def _line_from_location(location: object) -> int | None:
        if not isinstance(location, Mapping):
            return None

        return SonarQubeClient._get_start_line(location.get("textRange"))

    @staticmethod
    def _end_line_from_location(location: object) -> int | None:
        if not isinstance(location, Mapping):
            return None

        return SonarQubeClient._get_end_line(location.get("textRange"))

    @staticmethod
    def _get_start_line(text_range: object) -> int | None:
        if isinstance(text_range, Mapping):
            start_line = text_range.get("startLine")
            if isinstance(start_line, int):
                return start_line
        return None

    @staticmethod
    def _get_end_line(text_range: object) -> int | None:
        if isinstance(text_range, Mapping):
            end_line = text_range.get("endLine")
            if isinstance(end_line, int):
                return end_line
        return None
