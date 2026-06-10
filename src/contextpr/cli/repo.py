from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import typer

from contextpr import __version__
from contextpr.cli.shared import GITHUB_APP_PRIVATE_KEY_PATH
from contextpr.config import REPO_CONFIG_FILE_NAME, REPO_STATE_DIR_NAME

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


def run_init(*, configure_secrets: bool, install_hook: bool) -> None:
    show_init_banner()
    root = repository_root()
    state_dir = animated_step(
        "Preparing repository state",
        lambda: ensure_repo_state(root),
    )
    animated_step(
        "Updating gitignore",
        lambda: ensure_repo_gitignore_entries(root, GITIGNORE_ENTRIES),
    )
    if install_hook:
        animated_step(
            "Installing commit guard",
            lambda: install_pre_commit_hook(root),
        )
    ensure_private_key_drawer(root)
    if configure_secrets:
        configure_local_credentials(root)

    tracked = tracked_local_paths(root)
    typer.echo(f"ContextPR initialized in {state_dir}.")
    typer.echo(f"Local history database will be stored at {state_dir / 'history.db'}.")
    if tracked:
        typer.echo(
            "Warning: local ContextPR paths are already tracked by git. "
            f"Run: git rm -r --cached {' '.join(tracked)}"
        )


def run_guard() -> None:
    root = repository_root()
    tracked = tracked_local_paths(root)
    if tracked:
        raise typer.BadParameter(
            "ContextPR local state or secrets are tracked by git: "
            f"{', '.join(tracked)}. Remove them with git rm --cached."
        )
    typer.echo("ContextPR guard passed: no local state or secrets are tracked.")


def repository_root() -> Path:
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


def show_init_banner() -> None:
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


def animated_step[T](label: str, action: Callable[[], T]) -> T:
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


def ensure_repo_state(root: Path) -> Path:
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


def ensure_repo_gitignore_entries(root: Path, entries: tuple[str, ...]) -> None:
    path = safe_repo_file(root, ".gitignore")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    missing = [entry for entry in entries if entry not in lines]
    if not missing:
        return
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    path.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def safe_repo_file(root: Path, filename: str) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / filename).resolve(strict=False)
    if candidate.parent != resolved_root or candidate.name != filename:
        raise typer.BadParameter(f"Refusing to write outside repository root: {filename}")
    return candidate


def install_pre_commit_hook(root: Path) -> None:
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


def ensure_private_key_drawer(root: Path) -> None:
    destination = root / GITHUB_APP_PRIVATE_KEY_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        raise typer.BadParameter(
            "ContextPR requires the GitHub App private key at "
            f"{destination}. Place the PEM there and rerun `context-pr init`."
        )

    private_key = destination.read_text(encoding="utf-8").strip()
    if "BEGIN" not in private_key or "PRIVATE KEY" not in private_key:
        raise typer.BadParameter(
            "The GitHub App private key at "
            f"{destination} does not look like a PEM key."
        )


def configure_local_credentials(root: Path) -> None:
    env_path = root / ".env"
    values = read_env_values(env_path)
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
    write_env_values(env_path, values)
    typer.echo(f"Wrote local secrets to {env_path}.")
    typer.echo(
        "Using GitHub App private key from "
        f"{root / GITHUB_APP_PRIVATE_KEY_PATH}."
    )


def read_env_values(path: Path) -> dict[str, str]:
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


def write_env_values(path: Path, values: dict[str, str]) -> None:
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


def tracked_local_paths(root: Path) -> list[str]:
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
