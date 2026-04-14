"""SonarQube and SonarCloud integration placeholders."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from contextpr.config import Settings
from contextpr.models import IssueLocation, SonarIssue


class SonarQubeClient:
    """Placeholder client for SonarQube and SonarCloud pull request analysis."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the client with application settings."""
        self._settings = settings

    def is_configured(self) -> bool:
        """Return whether the client has enough configuration to operate."""
        return self._settings.sonar_enabled

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
        """Fetch issues associated with a pull request analysis.

        Future implementations can map Sonar API responses into typed domain models.
        """
        self._settings.require("sonar_token", "sonar_project_key")

        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "pullRequest": str(pull_request_number),
                "resolved": "false",
            }
        )
        request = Request(
            url=f"{self._api_url('/api/issues/search')}?{params}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._basic_auth_token()}",
            },
        )

        with urlopen(request) as response:
            payload = json.load(response)

        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            return []

        return [issue for raw_issue in issues if (issue := self._map_issue(raw_issue)) is not None]

    def fetch_quality_gate_status(self, pull_request_number: int) -> str:
        """Fetch the quality gate status for a pull request analysis."""
        raise NotImplementedError("SonarQube quality gate retrieval is not implemented yet.")

    def _api_url(self, path: str) -> str:
        """Build a full Sonar API URL from a relative path."""
        base_url = self._settings.sonar_host_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    def _basic_auth_token(self) -> str:
        """Build the Basic auth value expected by Sonar APIs."""
        token = self._settings.sonar_token or ""
        return base64.b64encode(f"{token}:".encode()).decode("ascii")

    @staticmethod
    def _map_issue(payload: Mapping[str, object]) -> SonarIssue | None:
        """Convert a Sonar API issue payload into a typed model."""
        component = payload.get("component")
        if not isinstance(component, str) or ":" not in component:
            return None

        issue_key = payload.get("key")
        rule = payload.get("rule")
        severity = payload.get("severity")
        message = payload.get("message")
        line = SonarQubeClient._extract_line(payload)

        if not all(isinstance(value, str) for value in (issue_key, rule, severity, message)):
            return None

        path = component.split(":", maxsplit=1)[1]
        return SonarIssue(
            key=cast(str, issue_key),
            rule=cast(str, rule),
            severity=cast(str, severity),
            message=cast(str, message),
            location=IssueLocation(path=path, line=line),
        )

    @staticmethod
    def _extract_line(payload: Mapping[str, object]) -> int | None:
        """Extract the most useful line number from a Sonar issue payload."""
        text_range = payload.get("textRange")
        if isinstance(text_range, Mapping):
            start_line = text_range.get("startLine")
            if isinstance(start_line, int):
                return start_line

        flows = payload.get("flows")
        if not isinstance(flows, list):
            return None

        for flow in flows:
            if not isinstance(flow, Mapping):
                continue

            locations = flow.get("locations")
            if not isinstance(locations, list):
                continue

            for location in locations:
                if not isinstance(location, Mapping):
                    continue

                text_range = location.get("textRange")
                if isinstance(text_range, Mapping):
                    start_line = text_range.get("startLine")
                    if isinstance(start_line, int):
                        return start_line

        return None
