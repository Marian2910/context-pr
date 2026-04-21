from __future__ import annotations

import logging
from typing import Annotated

import typer

from contextpr import __version__
from contextpr.config import Settings
from contextpr.enrichment import IssueEnricher
from contextpr.integrations.github import GitHubClient
from contextpr.integrations.sonarqube import SonarQubeClient
from contextpr.logging_config import configure_logging
from contextpr.models import PullRequestRef
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
    service = AnalysisService(
        github_client=GitHubClient(settings),
        sonar_client=SonarQubeClient(settings),
        issue_enricher=IssueEnricher(
            model_path=settings.intent_model_path,
            dataset_path=settings.issue_dataset_path,
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
