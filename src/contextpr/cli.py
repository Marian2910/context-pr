from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from contextpr import __version__
from contextpr.config import REPO_CONFIG_FILE_NAME, REPO_STATE_DIR_NAME, Settings
from contextpr.enrichment import IssueEnricher
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
analyze_app = typer.Typer(help="Analyze pull requests.", no_args_is_help=True)
app.add_typer(analyze_app, name="analyze")

GITIGNORE_ENTRIES = (
    f"{REPO_STATE_DIR_NAME}/",
    ".env",
    "secrets/",
)
PRE_COMMIT_HOOK = f"""#!/bin/sh
blocked="$(git diff --cached --name-only -- {REPO_STATE_DIR_NAME} .env secrets)"
if [ -n "$blocked" ]; then
  echo "ContextPR refuses to commit local state or secrets:" >&2
  echo "$blocked" >&2
  echo "Remove these paths from the index before committing." >&2
  exit 1
fi
"""


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


def _analyze_pull_request(
    *,
    pr_number: int,
    dry_run: bool,
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

    pull_request = PullRequestRef(
        repository=settings.github_repository or "",
        number=pr_number,
    )
    github_client = GitHubClient(settings)
    sonar_client = SonarQubeClient(settings)
    history_store = (
        HistoryStore(settings.local_history_db_path) if settings.local_history_enabled else None
    )
    local_git_enabled = False
    if settings.local_history_enabled:
        assert history_store is not None
        local_git_enabled = _sync_local_history(
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
    _analyze_pull_request(pr_number=pr_number, dry_run=dry_run)


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
    _analyze_pull_request(pr_number=pr_number, dry_run=dry_run)


def run() -> None:
    app()


@app.command()
def init(
    configure_secrets: Annotated[
        bool,
        typer.Option(
            "--configure-secrets/--no-configure-secrets",
            help=(
                "Prompt for GitHub and Sonar credentials and write them to a "
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
    _show_init_banner()
    root = _repository_root()
    state_dir = _animated_step(
        "Preparing repository state",
        lambda: _ensure_repo_state(root),
    )
    _animated_step(
        "Updating gitignore",
        lambda: _ensure_gitignore_entries(root / ".gitignore", GITIGNORE_ENTRIES),
    )
    if install_hook:
        _animated_step(
            "Installing commit guard",
            lambda: _install_pre_commit_hook(root),
        )
    if configure_secrets:
        _configure_local_credentials(root)

    tracked = _tracked_local_paths(root)
    typer.echo(f"ContextPR initialized in {state_dir}.")
    typer.echo(f"Local history database will be stored at {state_dir / 'history.db'}.")
    if tracked:
        typer.echo(
            "Warning: local ContextPR paths are already tracked by git. "
            f"Run: git rm -r --cached {' '.join(tracked)}"
        )


@app.command("sync-history")
def sync_history() -> None:
    _sync_history_command()


@app.command("sync")
def sync() -> None:
    _sync_history_command()


@app.command()
def guard() -> None:
    root = _repository_root()
    tracked = _tracked_local_paths(root)
    if tracked:
        raise typer.BadParameter(
            "ContextPR local state or secrets are tracked by git: "
            f"{', '.join(tracked)}. Remove them with git rm --cached."
        )
    typer.echo("ContextPR guard passed: no local state or secrets are tracked.")


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
    typer.echo(f"ContextPR current version: {__version__}")
    command = _update_command(source)
    typer.echo(f"Running: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
    typer.echo("ContextPR update completed. Run `context-pr --version` to confirm.")


def _sync_history_command() -> None:
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


def _repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise typer.BadParameter("ContextPR init must be run inside a git repository.")
    return Path(result.stdout.strip()).resolve()


def _show_init_banner() -> None:
    if not sys.stdout.isatty():
        return
    typer.echo(
        f"""
  ######   #######  ##    ## ######## ######## ##     ## ########
 ##    ## ##     ## ###   ##    ##    ##        ##   ##     ##
 ##       ##     ## ####  ##    ##    ##         ## ##      ##
 ##       ##     ## ## ## ##    ##    ######      ###       ##
 ##       ##     ## ##  ####    ##    ##         ## ##      ##
 ##    ## ##     ## ##   ###    ##    ##        ##   ##     ##
  ######   #######  ##    ##    ##    ######## ##     ##    ##

        ########  ########
        ##     ## ##     ##
        ##     ## ##     ##
        ########  ########
        ##        ##   ##
        ##        ##    ##
        ##        ##     ##

ContextPR release {__version__}
"""
    )


def _animated_step[T](label: str, action: Callable[[], T]) -> T:
    if not sys.stdout.isatty():
        return action()

    frames = ("|", "/", "-", "\\")
    typer.echo(f"{label} ", nl=False)
    started_at = time.monotonic()
    try:
        result = action()
        while time.monotonic() - started_at < 0.35:
            frame = frames[int((time.monotonic() - started_at) * 12) % len(frames)]
            typer.echo(f"\r{label} {frame}", nl=False)
            time.sleep(0.08)
    except Exception:
        typer.echo(f"\r{label} failed")
        raise

    typer.echo(f"\r{label} done ")
    return result


def _ensure_repo_state(root: Path) -> Path:
    state_dir = root / REPO_STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / REPO_CONFIG_FILE_NAME
    if not config_path.exists():
        config_path.write_text(
            "\n".join(
                (
                    'github_repository = ""',
                    'sonar_project_key = ""',
                    'sonar_organization = ""',
                    'sonar_host_url = "https://sonarcloud.io"',
                    "local_history_enabled = true",
                    "",
                )
            ),
            encoding="utf-8",
        )
    return state_dir


def _ensure_gitignore_entries(path: Path, entries: tuple[str, ...]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    missing = [entry for entry in entries if entry not in lines]
    if not missing:
        return
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    path.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def _install_pre_commit_hook(root: Path) -> None:
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        typer.echo("Skipping pre-commit hook installation because .git/hooks was not found.")
        return
    hook_path = hooks_dir / "pre-commit"
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if "ContextPR refuses to commit local state or secrets" in existing:
            return
        hook_path.write_text(existing.rstrip() + "\n\n" + PRE_COMMIT_HOOK, encoding="utf-8")
    else:
        hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | 0o111)


def _configure_local_credentials(root: Path) -> None:
    env_path = root / ".env"
    values = _read_env_values(env_path)
    values.update(
        {
            "CONTEXTPR_GITHUB_APP_ID": typer.prompt(
                "GitHub App ID",
                default=values.get("CONTEXTPR_GITHUB_APP_ID")
                or os.environ.get("CONTEXTPR_GITHUB_APP_ID")
                or "",
            ),
            "CONTEXTPR_GITHUB_INSTALLATION_ID": typer.prompt(
                "GitHub App installation ID",
                default=values.get("CONTEXTPR_GITHUB_INSTALLATION_ID")
                or os.environ.get("CONTEXTPR_GITHUB_INSTALLATION_ID")
                or "",
            ),
        }
    )
    _write_github_app_private_key(root)
    values.update(
        {
            "CONTEXTPR_SONAR_TOKEN": typer.prompt(
                "Sonar token",
                default=values.get("CONTEXTPR_SONAR_TOKEN")
                or os.environ.get("CONTEXTPR_SONAR_TOKEN")
                or "",
                hide_input=True,
            ),
            "CONTEXTPR_GITHUB_REPOSITORY": typer.prompt(
                "GitHub repository, for example owner/repo",
                default=values.get("CONTEXTPR_GITHUB_REPOSITORY")
                or os.environ.get("CONTEXTPR_GITHUB_REPOSITORY")
                or "",
            ),
            "CONTEXTPR_SONAR_PROJECT_KEY": typer.prompt(
                "Sonar project key",
                default=values.get("CONTEXTPR_SONAR_PROJECT_KEY")
                or os.environ.get("CONTEXTPR_SONAR_PROJECT_KEY")
                or "",
            ),
            "CONTEXTPR_SONAR_ORGANIZATION": typer.prompt(
                "Sonar organization",
                default=values.get("CONTEXTPR_SONAR_ORGANIZATION")
                or os.environ.get("CONTEXTPR_SONAR_ORGANIZATION")
                or "",
            ),
            "CONTEXTPR_ENABLE_LOCAL_HISTORY": "true",
            "CONTEXTPR_LOCAL_HISTORY_DB_PATH": str(root / REPO_STATE_DIR_NAME / "history.db"),
        }
    )
    _write_env_values(env_path, values)
    typer.echo(f"Wrote local secrets to {env_path}.")
    typer.echo(
        "Wrote GitHub App private key to "
        f"{root / 'secrets' / 'GITHUB_APP_PRIVATE_KEY.pem'}."
    )


def _write_github_app_private_key(root: Path) -> None:
    destination = root / "secrets" / "GITHUB_APP_PRIVATE_KEY.pem"
    existing_default = str(destination) if destination.is_file() else ""
    source = typer.prompt(
        "GitHub App private key PEM file path",
        default=existing_default,
    )
    source_path = Path(source).expanduser()
    if not source_path.is_file():
        raise typer.BadParameter(f"GitHub App private key file does not exist: {source_path}")

    private_key = source_path.read_text(encoding="utf-8").strip()
    if "BEGIN" not in private_key or "PRIVATE KEY" not in private_key:
        raise typer.BadParameter("GitHub App private key file does not look like a PEM key.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(private_key + "\n", encoding="utf-8")


def _read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_values(path: Path, values: dict[str, str]) -> None:
    remaining = {key for key, value in values.items() if value}
    output: list[str] = []
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in raw_line:
                output.append(raw_line)
                continue
            key, _value = raw_line.split("=", 1)
            normalized_key = key.strip()
            if normalized_key in values and values[normalized_key]:
                output.append(f"{normalized_key}={values[normalized_key]}")
                remaining.discard(normalized_key)
            else:
                output.append(raw_line)

    if output and output[-1].strip():
        output.append("")
    output.extend(f"{key}={values[key]}" for key in values if key in remaining)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _tracked_local_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", REPO_STATE_DIR_NAME, ".env", "secrets"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _update_command(source: str) -> list[str]:
    executable = Path(sys.executable)
    if (
        executable.parent.name == "bin"
        and executable.parent.parent.name == "contextpr"
        and executable.parent.parent.parent.name == "venvs"
        and executable.parent.parent.parent.parent.name == "pipx"
    ):
        return ["pipx", "upgrade", "contextpr"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", source]
