from __future__ import annotations

from typing import Annotated

import typer

from contextpr import __version__
from contextpr.cli.analysis import analyze_pull_request, sync_history_command
from contextpr.cli.maintenance import help_text, run_uninstall, run_update
from contextpr.cli.repo import run_guard, run_init, safe_repo_file

app = typer.Typer(
    help=(
        "ContextPR reads SonarQube pull request analysis results and prepares "
        "contextual feedback for GitHub pull requests."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
analyze_app = typer.Typer(help="Analyze pull requests.", no_args_is_help=True)
app.add_typer(analyze_app, name="analyze")
_safe_repo_file = safe_repo_file


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
) -> None: ...


@analyze_app.callback(invoke_without_command=True)
def analyze(
    ctx: typer.Context,
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
    if ctx.invoked_subcommand is not None:
        return
    if pr_number is None:
        raise typer.BadParameter("A pull request number is required for analyze.")
    analyze_pull_request(pr_number=pr_number, dry_run=dry_run)


@analyze_app.command("pr")
def analyze_pr(
    pr_number: Annotated[int, typer.Argument(min=1, help="Pull request number to analyze.")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Preview the future analysis flow without posting comments.",
        ),
    ] = True,
) -> None:
    analyze_pull_request(pr_number=pr_number, dry_run=dry_run)


def run() -> None:
    app()


@app.command()
def init(
    configure_secrets: Annotated[
        bool,
        typer.Option(
            "--configure-secrets/--no-configure-secrets",
            help=(
                "Prompt for GitHub App and Sonar credentials and write them to a "
                "gitignored .env file."
            ),
        ),
    ] = True,
    install_hook: Annotated[
        bool,
        typer.Option(
            "--install-hook/--no-install-hook",
            help="Install a local pre-commit guard for ContextPR state and secrets.",
        ),
    ] = True,
) -> None:
    run_init(configure_secrets=configure_secrets, install_hook=install_hook)


@app.command("sync-history")
def sync_history() -> None:
    sync_history_command()


@app.command("sync")
def sync() -> None:
    sync_history_command()


@app.command()
def guard() -> None:
    run_guard()


@app.command()
def update(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            help="Package spec to install when updating outside pipx.",
        ),
    ] = "git+https://github.com/Marian2910/context-pr.git",
) -> None:
    run_update(source)


@app.command()
def uninstall() -> None:
    run_uninstall()


@app.command("help")
def help_command() -> None:
    typer.echo(help_text())
