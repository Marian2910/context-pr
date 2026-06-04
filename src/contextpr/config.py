from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Self

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITHUB_APP_PRIVATE_KEY_PATH = Path("secrets/GITHUB_APP_PRIVATE_KEY.pem")
DEFAULT_ISSUE_DATASET_PATH = Path("dataset/curated_issues_data.xlsx")
DEFAULT_LOCAL_HISTORY_DB_PATH = Path.home() / ".contextpr" / "history.db"
REPO_STATE_DIR_NAME = ".context-pr"
REPO_CONFIG_FILE_NAME = "config.toml"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOCAL_HISTORY_ENABLED = False
DEFAULT_SONAR_HOST_URL = "https://sonarcloud.io"


class ConfigurationError(ValueError):
    """Raised when required configuration values are missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    github_token: str | None = None
    github_app_id: str | None = None
    github_installation_id: str | None = None
    github_private_key: str | None = None
    github_api_url: str = DEFAULT_GITHUB_API_URL
    github_repository: str | None = None
    sonar_token: str | None = None
    sonar_host_url: str = DEFAULT_SONAR_HOST_URL
    sonar_organization: str | None = None
    sonar_project_key: str | None = None
    issue_dataset_path: Path = DEFAULT_ISSUE_DATASET_PATH
    local_history_db_path: Path = DEFAULT_LOCAL_HISTORY_DB_PATH
    local_history_enabled: bool = DEFAULT_LOCAL_HISTORY_ENABLED
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        env = os.environ if environ is None else environ
        local_config = _read_local_config()
        return cls(
            github_token=(
                _read_optional(env, "CONTEXTPR_GITHUB_TOKEN") or _read_optional(env, "GITHUB_TOKEN")
            ),
            github_app_id=_read_optional(env, "CONTEXTPR_GITHUB_APP_ID"),
            github_installation_id=_read_optional(env, "CONTEXTPR_GITHUB_INSTALLATION_ID"),
            github_private_key=_read_github_private_key(),
            github_api_url=_read_optional(
                env,
                "CONTEXTPR_GITHUB_API_URL",
                default=DEFAULT_GITHUB_API_URL,
            )
            or DEFAULT_GITHUB_API_URL,
            github_repository=_read_optional(
                env,
                "CONTEXTPR_GITHUB_REPOSITORY",
                default=_read_config_string(local_config, "github_repository"),
            ),
            sonar_token=_read_optional(env, "CONTEXTPR_SONAR_TOKEN"),
            sonar_host_url=_read_optional(
                env,
                "CONTEXTPR_SONAR_HOST_URL",
                default=_read_config_string(
                    local_config,
                    "sonar_host_url",
                    default=DEFAULT_SONAR_HOST_URL,
                ),
            )
            or DEFAULT_SONAR_HOST_URL,
            sonar_organization=_read_optional(
                env,
                "CONTEXTPR_SONAR_ORGANIZATION",
                default=_read_config_string(local_config, "sonar_organization"),
            ),
            sonar_project_key=_read_optional(
                env,
                "CONTEXTPR_SONAR_PROJECT_KEY",
                default=_read_config_string(local_config, "sonar_project_key"),
            ),
            issue_dataset_path=_read_path(
                env,
                "CONTEXTPR_ISSUE_DATASET_PATH",
                default=DEFAULT_ISSUE_DATASET_PATH,
            ),
            local_history_db_path=_read_path(
                env,
                "CONTEXTPR_LOCAL_HISTORY_DB_PATH",
                default=default_local_history_db_path(),
            ),
            local_history_enabled=_read_bool(
                env,
                "CONTEXTPR_ENABLE_LOCAL_HISTORY",
                default=_read_config_bool(
                    local_config,
                    "local_history_enabled",
                    default=DEFAULT_LOCAL_HISTORY_ENABLED,
                ),
            ),
            log_level=(
                _read_optional(env, "CONTEXTPR_LOG_LEVEL", default=DEFAULT_LOG_LEVEL)
                or DEFAULT_LOG_LEVEL
            ).upper(),
        )

    @property
    def github_enabled(self) -> bool:
        return bool(
            (self.github_app_enabled or self.github_token_enabled) and self.github_repository
        )

    @property
    def github_app_enabled(self) -> bool:
        return bool(self.github_app_id and self.github_installation_id and self.github_private_key)

    @property
    def github_token_enabled(self) -> bool:
        return bool(self.github_token)

    @property
    def github_auth_mode(self) -> str:
        if self.github_app_enabled:
            return "app"
        if self.github_token_enabled:
            return "token"
        return "none"

    @property
    def sonar_enabled(self) -> bool:
        return bool(self.sonar_token and self.sonar_project_key)

    def require(self, *field_names: str) -> None:
        missing = [field_name for field_name in field_names if not getattr(self, field_name)]
        if missing:
            formatted = ", ".join(sorted(missing))
            raise ConfigurationError(f"Missing required configuration values: {formatted}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def _read_optional(
    environ: Mapping[str, str],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    raw_value = environ.get(key)
    if raw_value is None:
        return default

    value = raw_value.strip()
    return value or default


def _read_github_private_key() -> str | None:
    key_path = _working_tree_root() / DEFAULT_GITHUB_APP_PRIVATE_KEY_PATH
    if not key_path.is_file():
        return None

    value = key_path.read_text(encoding="utf-8").strip()
    return value or None


def default_local_history_db_path() -> Path:
    root = _find_git_root(Path.cwd())
    if root is None:
        return DEFAULT_LOCAL_HISTORY_DB_PATH
    return root / REPO_STATE_DIR_NAME / "history.db"


def _working_tree_root() -> Path:
    return _find_git_root(Path.cwd()) or Path.cwd()


def _find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _read_local_config() -> Mapping[str, object]:
    config_path = _working_tree_root() / REPO_STATE_DIR_NAME / REPO_CONFIG_FILE_NAME
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _read_config_string(
    config: Mapping[str, object],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    value = config.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid string value for {REPO_STATE_DIR_NAME}/{key}.")
    normalized = value.strip()
    return normalized or default


def _read_config_bool(
    config: Mapping[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    value = config.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigurationError(f"Invalid boolean value for {REPO_STATE_DIR_NAME}/{key}.")
    return value


def _read_path(
    environ: Mapping[str, str],
    key: str,
    *,
    default: Path,
) -> Path:
    value = _read_optional(environ, key)
    if value is None:
        return default

    return Path(value).expanduser()


def _read_bool(
    environ: Mapping[str, str],
    key: str,
    *,
    default: bool,
) -> bool:
    value = _read_optional(environ, key)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ConfigurationError(f"Invalid boolean value for {key}: {value}")
