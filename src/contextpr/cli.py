"""Command line interface for ContextPR."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from contextpr import __version__
from contextpr.config import Settings
from contextpr.logging_config import configure_logging

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
    """Print the installed package version and exit."""
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
    """Initialize the command line interface."""


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
    """Run the placeholder analysis pipeline."""
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    target = f"PR #{pr_number}" if pr_number is not None else "the configured pull request"
    logger.info(
        "Analyze command invoked.",
        extra={"pr_number": pr_number or "auto", "dry_run": dry_run},
    )
    typer.echo(
        "ContextPR scaffold is installed. "
        f"Placeholder analyze command invoked for {target}. "
        "GitHub and SonarQube integrations will be implemented in a later step."
    )


def run() -> None:
    """Execute the ContextPR CLI application."""
    app()
