from __future__ import annotations

from collections.abc import Mapping
from urllib.request import urlopen

from contextpr.config import Settings
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore

from . import mapper as sonarqube_mapper
from .client import SonarQubeHttpClient
from .history import SonarProjectHistorySync
from .types import LOCAL_SONAR_SYNC_SOURCE as LOCAL_SONAR_SYNC_SOURCE
from .types import PROJECT_HISTORY_PAGE_SIZE, SonarProjectHistorySyncResult

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

        request = self._http_client.build_issues_request(pull_request_number)
        payload = self._http_client.execute_request(request)

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

    @staticmethod
    def _map_issue(payload: Mapping[str, object]) -> SonarIssue | None:
        return sonarqube_mapper.map_issue(payload)
