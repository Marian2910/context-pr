from __future__ import annotations

from collections.abc import Mapping
from urllib.request import Request, urlopen

from contextpr.config import Settings
from contextpr.integrations import sonarqube_mapper
from contextpr.integrations.sonarqube_client import SonarQubeHttpClient
from contextpr.integrations.sonarqube_history import (
    SonarProjectHistorySync,
    accumulate_page_result,
    should_stop_history_pagination,
)
from contextpr.integrations.sonarqube_types import (
    LOCAL_SONAR_SYNC_SOURCE as LOCAL_SONAR_SYNC_SOURCE,
)
from contextpr.integrations.sonarqube_types import (
    PROJECT_HISTORY_PAGE_SIZE,
    SonarProjectHistoryPageResult,
    SonarProjectHistorySyncResult,
)
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore, SonarIssueRecord

__all__ = [
    "LOCAL_SONAR_SYNC_SOURCE",
    "SonarProjectHistorySyncResult",
    "SonarQubeClient",
]


class SonarQubeClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http_client = SonarQubeHttpClient(settings, lambda request: urlopen(request))
        self._history_sync = SonarProjectHistorySync(self._http_client)

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
            if isinstance(raw_issue, Mapping)
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
        return self._history_sync.sync_project_issue_history(
            store=store,
            repository_key=repository_key,
            page_size=page_size,
        )

    def _sync_project_history_for_resolution_state(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int,
        resolved_filter: str,
        previous_cursor: str | None,
        latest_update: str | None,
        counters: dict[str, int],
    ) -> str | None:
        return self._history_sync.sync_project_history_for_resolution_state(
            store=store,
            repository_key=repository_key,
            page_size=page_size,
            resolved_filter=resolved_filter,
            previous_cursor=previous_cursor,
            latest_update=latest_update,
            counters=counters,
        )

    def _execute_project_history_request(
        self,
        *,
        page_number: int,
        page_size: int,
        resolved_filter: str,
    ) -> Mapping[str, object]:
        return self._history_sync.execute_project_history_request(
            page_number=page_number,
            page_size=page_size,
            resolved_filter=resolved_filter,
        )

    @staticmethod
    def _accumulate_page_result(
        counters: dict[str, int],
        page_result: SonarProjectHistoryPageResult,
    ) -> None:
        accumulate_page_result(counters, page_result)

    @staticmethod
    def _should_stop_history_pagination(
        *,
        page_result: SonarProjectHistoryPageResult,
        total: object,
        page_number: int,
        page_size: int,
    ) -> bool:
        return should_stop_history_pagination(
            page_result=page_result,
            total=total,
            page_number=page_number,
            page_size=page_size,
        )

    def _persist_sync_state(
        self,
        store: HistoryStore,
        repository_key: str,
        latest_update: str | None,
    ) -> None:
        self._history_sync.persist_sync_state(store, repository_key, latest_update)

    def _sync_project_history_page(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        raw_issues: list[object],
        previous_cursor: str | None,
        latest_update: str | None,
    ) -> SonarProjectHistoryPageResult:
        return self._history_sync.sync_project_history_page(
            store=store,
            repository_key=repository_key,
            raw_issues=raw_issues,
            previous_cursor=previous_cursor,
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
        return self._history_sync.sync_project_issue_record(
            store=store,
            repository_key=repository_key,
            raw_issue=raw_issue,
            updated_at=updated_at,
        )

    def _build_issues_request(self, pull_request_number: int) -> Request:
        return self._http_client.build_issues_request(pull_request_number)

    def _build_project_history_request(
        self,
        page_number: int,
        page_size: int,
        *,
        resolved: str,
    ) -> Request:
        return self._http_client.build_project_history_request(
            page_number,
            page_size,
            resolved=resolved,
        )

    def _execute_request(self, request: Request) -> Mapping[str, object]:
        return self._http_client.execute_request(request)

    def _api_url(self, path: str) -> str:
        return self._http_client.api_url(path)

    def _basic_auth_token(self) -> str:
        return self._http_client.basic_auth_token()

    @staticmethod
    def _map_issue(payload: Mapping[str, object]) -> SonarIssue | None:
        return sonarqube_mapper.map_issue(payload)

    @staticmethod
    def _map_issue_record(payload: Mapping[str, object]) -> SonarIssueRecord | None:
        return sonarqube_mapper.map_issue_record(payload)

    @staticmethod
    def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
        return sonarqube_mapper.optional_string(payload, key)

    @staticmethod
    def _extract_issue_fields(
        payload: Mapping[str, object],
    ) -> tuple[str, str, str, str, int | None, int | None, str] | None:
        return sonarqube_mapper.extract_issue_fields(payload)

    @staticmethod
    def _extract_tags(payload: Mapping[str, object]) -> tuple[str, ...]:
        return sonarqube_mapper.extract_tags(payload)

    @staticmethod
    def _extract_string(payload: Mapping[str, object], key: str) -> str:
        return sonarqube_mapper.extract_string(payload, key)

    @staticmethod
    def _extract_start_line(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.extract_start_line(payload)

    @staticmethod
    def _extract_end_line(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.extract_end_line(payload)

    @staticmethod
    def _line_from_text_range(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.line_from_text_range(payload)

    @staticmethod
    def _end_line_from_text_range(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.end_line_from_text_range(payload)

    @staticmethod
    def _line_from_flows(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.line_from_flows(payload)

    @staticmethod
    def _end_line_from_flows(payload: Mapping[str, object]) -> int | None:
        return sonarqube_mapper.end_line_from_flows(payload)

    @staticmethod
    def _line_from_flow(flow: object) -> int | None:
        return sonarqube_mapper.line_from_flow(flow)

    @staticmethod
    def _end_line_from_flow(flow: object) -> int | None:
        return sonarqube_mapper.end_line_from_flow(flow)

    @staticmethod
    def _line_from_location(location: object) -> int | None:
        return sonarqube_mapper.line_from_location(location)

    @staticmethod
    def _end_line_from_location(location: object) -> int | None:
        return sonarqube_mapper.end_line_from_location(location)

    @staticmethod
    def _get_start_line(text_range: object) -> int | None:
        return sonarqube_mapper.get_start_line(text_range)

    @staticmethod
    def _get_end_line(text_range: object) -> int | None:
        return sonarqube_mapper.get_end_line(text_range)
