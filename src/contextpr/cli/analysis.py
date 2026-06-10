from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import typer

from contextpr.cli.shared import load_cli_settings
from contextpr.config import Settings
from contextpr.enrichment import IssueEnricher
from contextpr.integrations.github import (
    LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
    LOCAL_GITHUB_SYNC_SOURCE,
    GitHubClient,
)
from contextpr.integrations.sonarqube import SonarQubeClient
from contextpr.integrations.sonarqube.types import LOCAL_SONAR_SYNC_SOURCE
from contextpr.models import PullRequestRef
from contextpr.persistence import HistoryStore
from contextpr.services import AnalysisService

logger = logging.getLogger(__name__)
LOCAL_HISTORY_SYNC_FRESHNESS = timedelta(minutes=10)


def analyze_pull_request(*, pr_number: int, dry_run: bool) -> None:
    settings = load_cli_settings(
        required_fields=("github_repository", "sonar_token", "sonar_project_key")
    )

    pull_request = PullRequestRef(
        repository=settings.github_repository or "",
        number=pr_number,
    )
    history_store = _create_history_store(settings)
    local_git_enabled = _prepare_local_history(
        settings=settings,
        history_store=history_store,
        repository_key=pull_request.repository,
    )
    service = _build_analysis_service(
        settings=settings,
        history_store=history_store,
        repository_key=pull_request.repository,
        local_git_enabled=local_git_enabled,
    )

    logger.info(
        "Analyze command invoked.",
        extra={"pr_number": pr_number, "dry_run": dry_run},
    )
    result = service.analyze_pull_request(pull_request=pull_request, dry_run=dry_run)
    typer.echo(
        "ContextPR analyzed "
        f"PR #{result.pull_request.number}: fetched {result.fetched_issues} Sonar issues, "
        f"prepared {result.eligible_issues} inline comments, "
        f"deleted {result.deleted_comments} previous ContextPR comments, "
        f"posted {result.posted_comments}."
    )


def sync_history_command() -> None:
    settings = load_cli_settings(
        required_fields=("github_repository", "sonar_token", "sonar_project_key"),
        require_local_history=True,
    )

    history_store = HistoryStore(settings.local_history_db_path)
    github_client = GitHubClient(settings)
    sonar_client = SonarQubeClient(settings)
    sync_local_history(
        history_store=history_store,
        repository_key=settings.github_repository or "",
        github_client=github_client,
        sonar_client=sonar_client,
    )
    typer.echo(
        "ContextPR synchronized local history for "
        f"{settings.github_repository} into {settings.local_history_db_path}."
    )


def _create_history_store(settings: Settings) -> HistoryStore | None:
    if not settings.local_history_enabled:
        return None
    return HistoryStore(settings.local_history_db_path)


def _prepare_local_history(
    *,
    settings: Settings,
    history_store: HistoryStore | None,
    repository_key: str,
) -> bool:
    if not settings.local_history_enabled or history_store is None:
        return False

    if local_history_sync_is_fresh(
        history_store=history_store,
        repository_key=repository_key,
        max_age=LOCAL_HISTORY_SYNC_FRESHNESS,
    ):
        logger.info(
            "Skipped local history sync because the local index is fresh.",
            extra={
                "repository": repository_key,
                "freshness_seconds": int(LOCAL_HISTORY_SYNC_FRESHNESS.total_seconds()),
            },
        )
        return (
            history_store.get_sync_state(repository_key, LOCAL_GITHUB_COMMIT_SYNC_SOURCE)
            is not None
        )

    github_client = GitHubClient(settings)
    sonar_client = SonarQubeClient(settings)
    return sync_local_history(
        history_store=history_store,
        repository_key=repository_key,
        github_client=github_client,
        sonar_client=sonar_client,
    )


def _build_analysis_service(
    *,
    settings: Settings,
    history_store: HistoryStore | None,
    repository_key: str,
    local_git_enabled: bool,
) -> AnalysisService:
    return AnalysisService(
        github_client=GitHubClient(settings),
        sonar_client=SonarQubeClient(settings),
        issue_enricher=IssueEnricher(
            dataset_path=settings.issue_dataset_path,
            enable_local_history=settings.local_history_enabled,
            enable_local_git_history=local_git_enabled,
            history_store=history_store,
            repository_key=repository_key if settings.local_history_enabled else None,
        ),
    )


def sync_local_history(
    *,
    history_store: HistoryStore,
    repository_key: str,
    github_client: GitHubClient,
    sonar_client: SonarQubeClient,
) -> bool:
    sonar_sync_result = sonar_client.sync_project_issue_history(
        store=history_store,
        repository_key=repository_key,
    )
    logger.info(
        "Synchronized local Sonar issue history.",
        extra={
            "repository": repository_key,
            "pages_fetched": sonar_sync_result.pages_fetched,
            "issues_seen": sonar_sync_result.issues_seen,
            "issues_upserted": sonar_sync_result.issues_upserted,
            "observations_recorded": sonar_sync_result.observations_recorded,
            "latest_update": sonar_sync_result.latest_update,
        },
    )
    git_sync_result = github_client.sync_commit_history(
        store=history_store,
        repository_key=repository_key,
    )
    local_git_enabled = (
        git_sync_result.commits_upserted > 0 or git_sync_result.latest_commit_sha is not None
    )
    logger.info(
        "Synchronized repository commit history from GitHub.",
        extra={
            "repository": repository_key,
            "pages_fetched": git_sync_result.pages_fetched,
            "commits_seen": git_sync_result.commits_seen,
            "commits_upserted": git_sync_result.commits_upserted,
            "touches_recorded": git_sync_result.touches_recorded,
            "latest_commit_sha": git_sync_result.latest_commit_sha,
            "latest_authored_at": git_sync_result.latest_authored_at,
        },
    )
    github_sync_result = github_client.sync_repository_history(
        store=history_store,
        repository_key=repository_key,
    )
    logger.info(
        "Synchronized local GitHub PR/review history.",
        extra={
            "repository": repository_key,
            "pages_fetched": github_sync_result.pages_fetched,
            "pull_requests_seen": github_sync_result.pull_requests_seen,
            "pull_requests_upserted": github_sync_result.pull_requests_upserted,
            "files_recorded": github_sync_result.files_recorded,
            "review_comments_recorded": github_sync_result.review_comments_recorded,
            "latest_update": github_sync_result.latest_update,
        },
    )
    return local_git_enabled


def local_history_sync_is_fresh(
    *,
    history_store: HistoryStore,
    repository_key: str,
    max_age: timedelta,
) -> bool:
    now = datetime.now(UTC)
    for source_name in (
        LOCAL_SONAR_SYNC_SOURCE,
        LOCAL_GITHUB_COMMIT_SYNC_SOURCE,
        LOCAL_GITHUB_SYNC_SOURCE,
    ):
        state = history_store.get_sync_state(repository_key, source_name)
        if state is None or state.updated_at is None:
            return False
        checked_at = parse_sync_timestamp(state.updated_at)
        if checked_at is None or now - checked_at > max_age:
            return False
    return True


def parse_sync_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
