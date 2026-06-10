from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from typing import Protocol, cast
from urllib.parse import urlencode, urljoin
from urllib.request import Request

from contextpr.config import Settings


class JsonResponse(Protocol):
    def __enter__(self) -> JsonResponse: ...

    def __exit__(self, *_args: object) -> None: ...

    def read(self, size: int = -1, /) -> str | bytes: ...


UrlOpen = Callable[[Request], JsonResponse]


class SonarQubeHttpClient:
    def __init__(self, settings: Settings, urlopen: UrlOpen) -> None:
        self._settings = settings
        self._urlopen = urlopen

    def build_issues_request(self, pull_request_number: int) -> Request:
        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "pullRequest": str(pull_request_number),
                "resolved": "false",
            }
        )

        return Request(
            url=f"{self.api_url('/api/issues/search')}?{params}",
            headers=self._json_headers(),
        )

    def build_project_history_request(
        self,
        page_number: int,
        page_size: int,
        *,
        resolved: str,
    ) -> Request:
        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "ps": str(page_size),
                "p": str(page_number),
                "s": "UPDATE_DATE",
                "asc": "false",
                "resolved": resolved,
            }
        )

        return Request(
            url=f"{self.api_url('/api/issues/search')}?{params}",
            headers=self._json_headers(),
        )

    def execute_request(self, request: Request) -> Mapping[str, object]:
        with self._urlopen(request) as response:
            return cast(Mapping[str, object], json.load(response))

    def api_url(self, path: str) -> str:
        base_url = self._settings.sonar_host_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def basic_auth_token(self) -> str:
        token = self._settings.sonar_token or ""
        return base64.b64encode(f"{token}:".encode()).decode("ascii")

    def _json_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {self.basic_auth_token()}",
        }
