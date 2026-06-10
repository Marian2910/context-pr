from __future__ import annotations

import sys
from pathlib import Path

import typer

from contextpr.config import Settings
from contextpr.logging_config import configure_logging

GITHUB_APP_PRIVATE_KEY_PATH = "secrets/GITHUB_APP_PRIVATE_KEY.pem"


def load_cli_settings(
    *,
    required_fields: tuple[str, ...],
    require_local_history: bool = False,
) -> Settings:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    require_github_app_auth(settings)
    if require_local_history and not settings.local_history_enabled:
        raise typer.BadParameter("Local history sync requires CONTEXTPR_ENABLE_LOCAL_HISTORY=true.")
    settings.require(*required_fields)
    return settings


def require_github_app_auth(settings: Settings) -> None:
    if settings.github_auth_mode == "none":
        raise typer.BadParameter(
            "GitHub authentication is required. Configure the GitHub App credentials "
            "used by ContextPR."
        )


def is_pipx_install(executable: str | Path | None = None) -> bool:
    current = Path(executable or sys.executable)
    return bool(
        current.parent.name == "bin"
        and current.parent.parent.name == "contextpr"
        and current.parent.parent.parent.name == "venvs"
        and current.parent.parent.parent.parent.name == "pipx"
    )
