from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from contextpr.integrations import sonarqube_mapper
from contextpr.integrations.sonarqube_client import SonarQubeHttpClient
from contextpr.integrations.sonarqube_types import (
    LOCAL_SONAR_SYNC_SOURCE,
    SonarProjectHistoryPageResult,
    SonarProjectHistorySyncResult,
)
from contextpr.persistence import (
    HistoryStore,
    SonarIssueObservationRecord,
    SyncStateRecord,
)


class SonarProjectHistorySync:
    def __init__(self, http_client: SonarQubeHttpClient) -> None:
        self._http_client = http_client

    def sync_project_issue_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        page_size: int,
    ) -> SonarProjectHistorySyncResult:
        with store.acquire_repository_lock(repository_key):
            previous_state = store.get_sync_state(repository_key, LOCAL_SONAR_SYNC_SOURCE)
            previous_cursor = previous_state.cursor if previous_state is not None else None
            counters = {
                "pages_fetched": 0,
                "issues_seen": 0,
                "issues_upserted": 0,
                "observations_recorded": 0,
            }
            latest_update = previous_cursor

            for resolved_filter in ("false", "true"):
                latest_update = self.sync_project_history_for_resolution_state(
                    store=store,
                    repository_key=repository_key,
                    page_size=page_size,
                    resolved_filter=resolved_filter,
                    previous_cursor=previous_cursor,
                    latest_update=latest_update,
                    counters=counters,
                )

            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=counters["pages_fetched"],
                issues_seen=counters["issues_seen"],
                issues_upserted=counters["issues_upserted"],
                observations_recorded=counters["observations_recorded"],
                latest_update=latest_update,
            )

    def sync_project_history_for_resolution_state(
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
        page_number = 1
        while True:
            payload = self.execute_project_history_request(
                page_number=page_number,
                page_size=page_size,
                resolved_filter=resolved_filter,
            )
            counters["pages_fetched"] += 1
            raw_issues = payload.get("issues", [])
            total = payload.get("total", 0)
            if not isinstance(raw_issues, list):
                return latest_update

            page_result = self.sync_project_history_page(
                store=store,
                repository_key=repository_key,
                raw_issues=raw_issues,
                previous_cursor=previous_cursor,
                latest_update=latest_update,
            )
            accumulate_page_result(counters, page_result)
            latest_update = page_result.latest_update
            self.persist_sync_state(store, repository_key, latest_update)

            if should_stop_history_pagination(
                page_result=page_result,
                total=total,
                page_number=page_number,
                page_size=page_size,
            ):
                return latest_update
            page_number += 1

    def execute_project_history_request(
        self,
        *,
        page_number: int,
        page_size: int,
        resolved_filter: str,
    ) -> Mapping[str, object]:
        return self._http_client.execute_request(
            self._http_client.build_project_history_request(
                page_number,
                page_size,
                resolved=resolved_filter,
            )
        )

    def persist_sync_state(
        self,
        store: HistoryStore,
        repository_key: str,
        latest_update: str | None,
    ) -> None:
        if latest_update is None:
            return
        store.upsert_sync_state(
            SyncStateRecord(
                repository_key=repository_key,
                source_name=LOCAL_SONAR_SYNC_SOURCE,
                cursor=latest_update,
                updated_at=utc_now(),
            )
        )

    def sync_project_history_page(
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
            updated_at = sonarqube_mapper.optional_string(raw_issue, "updateDate")
            if previous_cursor and updated_at and updated_at <= previous_cursor:
                should_stop = True
                continue
            if updated_at and (latest_update is None or updated_at > latest_update):
                latest_update = updated_at

            synced = self.sync_project_issue_record(
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

    def sync_project_issue_record(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
        raw_issue: Mapping[str, object],
        updated_at: str | None,
    ) -> int | None:
        if (record := sonarqube_mapper.map_issue_record(raw_issue)) is None:
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


def accumulate_page_result(
    counters: dict[str, int],
    page_result: SonarProjectHistoryPageResult,
) -> None:
    counters["issues_seen"] += page_result.issues_seen
    counters["issues_upserted"] += page_result.issues_upserted
    counters["observations_recorded"] += page_result.observations_recorded


def should_stop_history_pagination(
    *,
    page_result: SonarProjectHistoryPageResult,
    total: object,
    page_number: int,
    page_size: int,
) -> bool:
    if page_result.should_stop:
        return True
    if not isinstance(total, int):
        return True
    return page_number * page_size >= total


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
