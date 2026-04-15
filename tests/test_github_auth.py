"""Tests for GitHub authentication helpers."""

import pytest

from contextpr.config import ConfigurationError, Settings
from contextpr.integrations.github_auth import GitHubAuth


def test_github_auth_uses_installation_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub App auth should produce an installation token."""
    monkeypatch.setattr(
        "contextpr.integrations.github_auth.create_installation_token",
        lambda **_kwargs: "installation-token",
    )
    auth = GitHubAuth(
        Settings(
            github_app_id="12345",
            github_installation_id="67890",
            github_private_key=(
                "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----"
            ),
            github_repository="octo/example",
        )
    )

    assert auth.auth_mode == "app"
    assert auth.get_token() == "installation-token"


def test_github_auth_uses_token_when_available() -> None:
    """Token auth should work without GitHub App credentials."""
    auth = GitHubAuth(
        Settings(
            github_token="workflow-token",
            github_repository="octo/example",
        )
    )

    assert auth.auth_mode == "token"
    assert auth.get_token() == "workflow-token"
    assert auth.get_actor_login() == "github-actions[bot]"


def test_github_auth_requires_app_credentials() -> None:
    """GitHub auth should fail when app credentials are missing."""
    auth = GitHubAuth(Settings(github_repository="octo/example"))

    with pytest.raises(ConfigurationError):
        auth.get_token()


def test_github_app_actor_login_uses_app_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub App actor login should match GitHub's bot naming convention."""
    monkeypatch.setattr(
        "contextpr.integrations.github_auth.get_app_slug",
        lambda **_kwargs: "contextpr",
    )
    auth = GitHubAuth(
        Settings(
            github_app_id="12345",
            github_installation_id="67890",
            github_private_key=(
                "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----"
            ),
            github_repository="octo/example",
        )
    )

    assert auth.get_actor_login() == "contextpr[bot]"
