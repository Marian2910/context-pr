from __future__ import annotations

from dataclasses import dataclass

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
