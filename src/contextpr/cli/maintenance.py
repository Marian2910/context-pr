from __future__ import annotations

import subprocess
import sys

import typer

from contextpr import __version__
from contextpr.cli.shared import GITHUB_APP_PRIVATE_KEY_PATH, is_pipx_install


def help_text() -> str:
    return f"""ContextPR {__version__}

ContextPR analyzes Sonar pull request findings and posts contextual GitHub PR feedback.

Common commands:
  context-pr init                         Set up ContextPR in the current git repository.
  context-pr sync                         Sync local Sonar, PR, review, and commit history.
  context-pr analyze pr 3 --no-dry-run    Analyze PR #3 and post GitHub comments.
  context-pr guard                        Check that local state and secrets are not tracked.
  context-pr update                       Upgrade the installed ContextPR CLI.
  context-pr uninstall                    Remove the installed ContextPR package.

Local files created by init:
  .context-pr/                            Repo-local config and history database.
  .env                                    GitHub App and Sonar settings.
  secrets/GITHUB_APP_PRIVATE_KEY.pem      GitHub App private key.

Before init can finish, place your GitHub App PEM at:
  secrets/GITHUB_APP_PRIVATE_KEY.pem

More detail:
  context-pr --help
  context-pr analyze --help
  context-pr --version
"""


def run_update(source: str) -> None:
    typer.echo(f"ContextPR current version: {__version__}")
    command = update_command(source)
    typer.echo(f"Running: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
    typer.echo("ContextPR update completed. Run `context-pr --version` to confirm.")
    typer.echo(
        "Before running `context-pr init`, place your GitHub App PEM at "
        f"`{GITHUB_APP_PRIVATE_KEY_PATH}` inside the target repository."
    )


def run_uninstall() -> None:
    command = uninstall_command()
    typer.echo("Uninstalling ContextPR.")
    typer.echo("Repo-local state such as .context-pr/, .env, and secrets/ will be left intact.")
    typer.echo(f"Running: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def update_command(source: str) -> list[str]:
    if is_pipx_install():
        return ["pipx", "upgrade", "contextpr"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", source]


def uninstall_command() -> list[str]:
    if is_pipx_install():
        return ["pipx", "uninstall", "contextpr"]
    return [sys.executable, "-m", "pip", "uninstall", "-y", "contextpr"]
