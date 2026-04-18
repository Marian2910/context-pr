import pytest

from contextpr.config import ConfigurationError, Settings


def test_settings_from_env_reads_expected_values(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    monkeypatch.setattr(
        "contextpr.config._read_github_private_key",
        lambda: private_key,
    )
    settings = Settings.from_env(
        {
            "CONTEXTPR_GITHUB_APP_ID": "12345",
            "CONTEXTPR_GITHUB_INSTALLATION_ID": "67890",
            "CONTEXTPR_GITHUB_API_URL": "https://ghe.example/api/v3",
            "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
            "CONTEXTPR_SONAR_TOKEN": "sonar-token",
            "CONTEXTPR_SONAR_HOST_URL": "https://sonarqube.example",
            "CONTEXTPR_SONAR_ORGANIZATION": "platform",
            "CONTEXTPR_SONAR_PROJECT_KEY": "contextpr",
            "CONTEXTPR_LOG_LEVEL": "debug",
        }
    )

    assert settings.github_app_id == "12345"
    assert settings.github_installation_id == "67890"
    assert settings.github_private_key == private_key
    assert settings.github_api_url == "https://ghe.example/api/v3"
    assert settings.github_repository == "octo/example"
    assert settings.github_enabled is True
    assert settings.sonar_enabled is True
    assert str(settings.intent_model_path) == "artifacts/intent_classifier.joblib"
    assert str(settings.issue_dataset_path) == "dataset/curated_issues_data.xlsx"
    assert settings.log_level == "DEBUG"


def test_require_raises_for_missing_values() -> None:
    settings = Settings.from_env({})

    with pytest.raises(ConfigurationError):
        settings.require("github_app_id", "sonar_token")


def test_github_app_settings_enable_github_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "contextpr.config._read_github_private_key",
        lambda: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
    )
    settings = Settings.from_env(
        {
            "CONTEXTPR_GITHUB_APP_ID": "12345",
            "CONTEXTPR_GITHUB_INSTALLATION_ID": "67890",
            "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
        }
    )

    assert settings.github_app_enabled is True
    assert settings.github_auth_mode == "app"
    assert settings.github_enabled is True


def test_github_token_enables_github_auth() -> None:
    """A token should enable GitHub auth without app credentials."""
    settings = Settings.from_env(
        {
            "CONTEXTPR_GITHUB_TOKEN": "workflow-token",
            "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
        }
    )

    assert settings.github_token_enabled is True
    assert settings.github_auth_mode == "token"
    assert settings.github_enabled is True
