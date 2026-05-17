from __future__ import annotations

import logging
from typing import Annotated

import typer

from contextpr import __version__
from contextpr.config import Settings
from contextpr.enrichment import (
    IssueEnricher,
    LLMVerbalizerSettings,
    LightweightLLMGuidanceVerbalizer,
)
from contextpr.integrations.github import GitHubClient
from contextpr.integrations.sonarqube import SonarQubeClient
from contextpr.logging_config import configure_logging
from contextpr.models import PullRequestRef
from contextpr.persistence import HistoryStore
from contextpr.services import AnalysisService

app = typer.Typer(
    help=(
        "ContextPR reads SonarQube pull request analysis results and prepares "
        "contextual feedback for GitHub pull requests."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
logger = logging.getLogger(__name__)


def version_callback(value: bool | None) -> None:
    if value:
        typer.echo(f"ContextPR {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            help="Show the installed ContextPR version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    ...


@app.command()
def analyze(
    pr_number: Annotated[
        int | None,
        typer.Option(
            "--pr-number",
            min=1,
            help="Pull request number to analyze.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Preview the future analysis flow without posting comments.",
        ),
    ] = True,
) -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if settings.github_auth_mode == "none":
        raise typer.BadParameter(
            "GitHub authentication is required. Configure CONTEXTPR_GITHUB_TOKEN "
            "or GitHub App credentials."
        )

    settings.require(
        "github_repository",
        "sonar_token",
        "sonar_project_key",
    )

    if pr_number is None:
        raise typer.BadParameter("A pull request number is required for analyze.")

    pull_request = PullRequestRef(
        repository=settings.github_repository or "",
        number=pr_number,
    )
    verbalizer = None
    if settings.llm_enabled:
        assert settings.llm_api_url is not None
        assert settings.llm_api_key is not None
        assert settings.llm_model is not None
        verbalizer = LightweightLLMGuidanceVerbalizer(
            LLMVerbalizerSettings(
                api_url=settings.llm_api_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
            )
        )
    github_client = GitHubClient(settings)
    sonar_client = SonarQubeClient(settings)
    history_store = HistoryStore(settings.local_history_db_path) if settings.local_history_enabled else None
    local_git_enabled = False
    if settings.local_history_enabled:
        assert history_store is not None
        local_git_enabled = _sync_local_history(
            settings=settings,
            history_store=history_store,
            repository_key=pull_request.repository,
            github_client=github_client,
            sonar_client=sonar_client,
        )

    service = AnalysisService(
        github_client=github_client,
        sonar_client=sonar_client,
        issue_enricher=IssueEnricher(
            dataset_path=settings.issue_dataset_path,
            guidance_verbalizer=verbalizer,
            enable_local_history=settings.local_history_enabled,
            enable_local_git_history=local_git_enabled,
            history_store=history_store,
            repository_key=pull_request.repository if settings.local_history_enabled else None,
        ),
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


def run() -> None:
    app()


@app.command("sync-history")
def sync_history() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if not settings.local_history_enabled:
        raise typer.BadParameter(
            "Local history sync requires CONTEXTPR_ENABLE_LOCAL_HISTORY=true."
        )

    settings.require(
        "github_repository",
        "sonar_token",
        "sonar_project_key",
    )

    history_store = HistoryStore(settings.local_history_db_path)
    github_client = GitHubClient(settings)
    sonar_client = SonarQubeClient(settings)
    _sync_local_history(
        settings=settings,
        history_store=history_store,
        repository_key=settings.github_repository or "",
        github_client=github_client,
        sonar_client=sonar_client,
    )
    typer.echo(
        "ContextPR synchronized local history for "
        f"{settings.github_repository} into {settings.local_history_db_path}."
    )


def _sync_local_history(
    *,
    settings: Settings,
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
    local_git_enabled = git_sync_result.commits_upserted > 0 or git_sync_result.latest_commit_sha is not None
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
