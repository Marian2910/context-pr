from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import jwt

from contextpr.config import ConfigurationError, Settings

logger = logging.getLogger(__name__)


def create_installation_token(
    *,
    api_url: str,
    app_id: str,
    installation_id: str,
    private_key: str,
) -> str:
    jwt_token = create_app_jwt(app_id=app_id, private_key=private_key)
    request = Request(
        url=_api_url(
            api_url,
            f"/app/installations/{installation_id}/access_tokens",
        ),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        data=b"{}",
        method="POST",
    )

    with urlopen(request) as response:
        payload = json.load(response)

    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("GitHub App installation token response did not include a token.")

    return token


def get_app_slug(*, api_url: str, app_id: str, private_key: str) -> str:
    jwt_token = create_app_jwt(app_id=app_id, private_key=private_key)
    request = Request(
        url=_api_url(api_url, "/app"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urlopen(request) as response:
        payload = json.load(response)

    slug = payload.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ValueError("GitHub App response did not include an app slug.")

    return slug


def create_app_jwt(*, app_id: str, private_key: str) -> str:
    now = datetime.now(tz=UTC)
    payload = {
        "iat": int((now - timedelta(seconds=60)).timestamp()),
        "exp": int((now + timedelta(minutes=9)).timestamp()),
        "iss": app_id,
    }
    encoded = jwt.encode(
        payload,
        _normalize_private_key(private_key),
        algorithm="RS256",
    )
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


class GitHubAuth:

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._installation_token: str | None = None
        self._app_slug: str | None = None

    @property
    def auth_mode(self) -> str:
        return self._settings.github_auth_mode

    def require_configured(self) -> None:
        if self.auth_mode == "none":
            raise ConfigurationError(
                "Missing GitHub authentication. Configure CONTEXTPR_GITHUB_TOKEN "
                "or GitHub App credentials."
            )

        if self.auth_mode == "token":
            self._settings.require("github_token")
            return

        self._settings.require(
            "github_app_id",
            "github_installation_id",
            "github_private_key",
        )

    def get_token(self) -> str:
        self.require_configured()
        if self.auth_mode == "token":
            logger.info("Using GitHub token authentication.")
            return self._settings.github_token or ""

        if self._installation_token is None:
            logger.info("Using GitHub App authentication.")
            self._installation_token = create_installation_token(
                api_url=self._settings.github_api_url,
                app_id=self._settings.github_app_id or "",
                installation_id=self._settings.github_installation_id or "",
                private_key=self._settings.github_private_key or "",
            )

        return self._installation_token

    def get_actor_login(self) -> str:
        self.require_configured()
        if self.auth_mode == "token":
            return "github-actions[bot]"

        if self._app_slug is None:
            self._app_slug = get_app_slug(
                api_url=self._settings.github_api_url,
                app_id=self._settings.github_app_id or "",
                private_key=self._settings.github_private_key or "",
            )

        return f"{self._app_slug}[bot]"


def _normalize_private_key(private_key: str) -> str:
    normalized = private_key.strip()
    if "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n")

    return normalized


def _api_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
