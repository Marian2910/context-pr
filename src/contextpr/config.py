"""Configuration loading for ContextPR."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Self

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)


class ConfigurationError(ValueError):
    """Raised when required configuration values are missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    github_repository: str | None = None
    sonar_token: str | None = None
    sonar_host_url: str = "https://sonarcloud.io"
    sonar_organization: str | None = None
    sonar_project_key: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Build settings from a mapping of environment variables."""
        env = os.environ if environ is None else environ
        return cls(
            github_token=_read_optional(env, "CONTEXTPR_GITHUB_TOKEN"),
            github_api_url=(
                _read_optional(
                    env,
                    "CONTEXTPR_GITHUB_API_URL",
                    default="https://api.github.com",
                )
                or "https://api.github.com"
            ),
            github_repository=_read_optional(env, "CONTEXTPR_GITHUB_REPOSITORY"),
            sonar_token=_read_optional(env, "CONTEXTPR_SONAR_TOKEN"),
            sonar_host_url=(
                _read_optional(
                    env,
                    "CONTEXTPR_SONAR_HOST_URL",
                    default="https://sonarcloud.io",
                )
                or "https://sonarcloud.io"
            ),
            sonar_organization=_read_optional(env, "CONTEXTPR_SONAR_ORGANIZATION"),
            sonar_project_key=_read_optional(env, "CONTEXTPR_SONAR_PROJECT_KEY"),
            log_level=(_read_optional(env, "CONTEXTPR_LOG_LEVEL", default="INFO") or "INFO").upper(),
        )

    @property
    def github_enabled(self) -> bool:
        """Return whether GitHub credentials look usable."""
        return bool(self.github_token and self.github_repository)

    @property
    def sonar_enabled(self) -> bool:
        """Return whether Sonar credentials look usable."""
        return bool(self.sonar_token and self.sonar_project_key)

    def require(self, *field_names: str) -> None:
        """Ensure the named settings fields are populated."""
        missing = [field_name for field_name in field_names if not getattr(self, field_name)]
        if missing:
            formatted = ", ".join(sorted(missing))
            raise ConfigurationError(f"Missing required configuration values: {formatted}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings.from_env()


def _read_optional(
    environ: Mapping[str, str],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    """Read and normalize an optional environment variable."""
    raw_value = environ.get(key)
    if raw_value is None:
        return default

    value = raw_value.strip()
    return value or default
