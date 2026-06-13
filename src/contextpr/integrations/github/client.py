from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request

from contextpr.config import Settings

from .auth import GitHubAuth


class GitHubApiClient:
    def __init__(
        self,
        settings: Settings,
        auth: GitHubAuth,
        urlopen: Callable[[Request], Any],
    ) -> None:
        self._settings = settings
        self._auth = auth
        self._urlopen = urlopen

    def require_configured(self) -> None:
        self._settings.require("github_repository")
        self._auth.require_configured()

    def get_json_list(self, path: str) -> list[Any]:
        payload = self.get_json(path)
        return payload if isinstance(payload, list) else []

    def get_json_mapping(self, path: str) -> Mapping[str, object]:
        payload = self.get_json(path)
        return payload if isinstance(payload, Mapping) else {}

    def get_json(self, path: str) -> object:
        self.require_configured()
        with self._urlopen(self.request(path)) as response:
            return json.load(response)

    def send_json(
        self,
        *,
        path: str,
        method: str,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        self.require_configured()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        with self._urlopen(self.request(path, method=method, data=body)):
            return None

    def request(
        self,
        path: str,
        *,
        method: str | None = None,
        data: bytes | None = None,
    ) -> Request:
        return Request(
            url=self.api_url(path),
            headers=self.headers(),
            data=data,
            method=method,
        )

    def api_url(self, path: str) -> str:
        base_url = self._settings.github_api_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def headers(self) -> dict[str, str]:
        token = self._auth.get_token()
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
