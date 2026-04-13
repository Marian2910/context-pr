"""Tests for configuration loading."""

import pytest

from contextpr.config import ConfigurationError, Settings


def test_settings_from_env_reads_expected_values() -> None:
    """Environment-backed settings should be mapped into the Settings model."""
    settings = Settings.from_env(
        {
            "CONTEXTPR_GITHUB_TOKEN": "gh-token",
            "CONTEXTPR_GITHUB_API_URL": "https://ghe.example/api/v3",
            "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
            "CONTEXTPR_SONAR_TOKEN": "sonar-token",
            "CONTEXTPR_SONAR_HOST_URL": "https://sonarqube.example",
            "CONTEXTPR_SONAR_ORGANIZATION": "platform",
            "CONTEXTPR_SONAR_PROJECT_KEY": "contextpr",
            "CONTEXTPR_LOG_LEVEL": "debug",
        }
    )

    assert settings.github_token == "gh-token"
    assert settings.github_api_url == "https://ghe.example/api/v3"
    assert settings.github_repository == "octo/example"
    assert settings.github_enabled is True
    assert settings.sonar_enabled is True
    assert settings.log_level == "DEBUG"


def test_require_raises_for_missing_values() -> None:
    """Missing required settings should raise a dedicated error."""
    settings = Settings.from_env({})

    with pytest.raises(ConfigurationError):
        settings.require("github_token", "sonar_token")
