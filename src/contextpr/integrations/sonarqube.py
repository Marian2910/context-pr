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

    def __init__(self, settings: Settings) -> None:
        """Initialize the client with application settings."""
        self._settings = settings

    def is_configured(self) -> bool:
        """Return whether the client has enough configuration to operate."""
        return self._settings.sonar_enabled

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
        """Fetch issues associated with a pull request analysis."""
        self._settings.require("sonar_token", "sonar_project_key")

        request = self._build_issues_request(pull_request_number)
        payload = self._execute_request(request)

        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            return []

        return [
            issue
            for raw_issue in issues
            if (issue := self._map_issue(raw_issue)) is not None
        ]

    def fetch_quality_gate_status(self, pull_request_number: int) -> str:
        """Fetch the quality gate status for a pull request analysis."""
        raise NotImplementedError("SonarQube quality gate retrieval is not implemented yet.")

    def _build_issues_request(self, pull_request_number: int) -> Request:
        """Build the HTTP request for fetching issues."""
        params = urlencode(
            {
                "componentKeys": self._settings.sonar_project_key,
                "pullRequest": str(pull_request_number),
                "resolved": "false",
            }
        )

        return Request(
            url=f"{self._api_url('/api/issues/search')}?{params}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._basic_auth_token()}",
            },
        )

    @staticmethod
    def _execute_request(request: Request) -> Mapping[str, object]:
        """Execute an HTTP request and return JSON payload."""
        with urlopen(request) as response:
            return cast(Mapping[str, object], json.load(response))

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

        fields = SonarQubeClient._extract_issue_fields(payload)
        if fields is None:
            return None

        path = component.split(":", maxsplit=1)[1]
        issue_key, rule, severity, message, line, issue_type = fields

        return SonarIssue(
            key=issue_key,
            rule=rule,
            severity=severity,
            message=message,
            location=IssueLocation(path=path, line=line),
            issue_type=issue_type,
            tags=SonarQubeClient._extract_tags(payload),
            clean_code_attribute=SonarQubeClient._extract_string(payload, "cleanCodeAttribute"),
            clean_code_attribute_category=SonarQubeClient._extract_string(
                payload,
                "cleanCodeAttributeCategory",
            ),
        )

    @staticmethod
    def _extract_issue_fields(
        payload: Mapping[str, object],
    ) -> tuple[str, str, str, str, int | None, str] | None:
        """Extract and validate issue fields."""
        issue_key = payload.get("key")
        rule = payload.get("rule")
        severity = payload.get("severity")
        message = payload.get("message")
        issue_type = payload.get("type")

        if not all(
            isinstance(value, str)
            for value in (issue_key, rule, severity, message, issue_type)
        ):
            return None

        return (
            cast(str, issue_key),
            cast(str, rule),
            cast(str, severity),
            cast(str, message),
            SonarQubeClient._extract_line(payload),
            cast(str, issue_type),
        )

    @staticmethod
    def _extract_tags(payload: Mapping[str, object]) -> tuple[str, ...]:
        """Extract issue tags from the Sonar payload."""
        tags = payload.get("tags")
        if not isinstance(tags, list):
            return ()

        return tuple(str(tag) for tag in tags if isinstance(tag, str))

    @staticmethod
    def _extract_string(payload: Mapping[str, object], key: str) -> str:
        """Extract a string field from the payload or return an empty value."""
        value = payload.get(key)
        if isinstance(value, str):
            return value

        return ""

    @staticmethod
    def _extract_line(payload: Mapping[str, object]) -> int | None:
        """Extract the most useful line number from a Sonar issue payload."""
        return (
            SonarQubeClient._line_from_text_range(payload)
            or SonarQubeClient._line_from_flows(payload)
        )

    @staticmethod
    def _line_from_text_range(payload: Mapping[str, object]) -> int | None:
        """Extract line directly from payload.textRange."""
        return SonarQubeClient._get_start_line(payload.get("textRange"))

    @staticmethod
    def _line_from_flows(payload: Mapping[str, object]) -> int | None:
        """Extract line from flows."""
        flows = payload.get("flows")
        if not isinstance(flows, list):
            return None

        for flow in flows:
            line = SonarQubeClient._line_from_flow(flow)
            if line is not None:
                return line

        return None

    @staticmethod
    def _line_from_flow(flow: object) -> int | None:
        """Extract line from a single flow."""
        if not isinstance(flow, Mapping):
            return None

        locations = flow.get("locations")
        if not isinstance(locations, list):
            return None

        for location in locations:
            line = SonarQubeClient._line_from_location(location)
            if line is not None:
                return line

        return None

    @staticmethod
    def _line_from_location(location: object) -> int | None:
        """Extract line from a single location."""
        if not isinstance(location, Mapping):
            return None

        return SonarQubeClient._get_start_line(location.get("textRange"))

    @staticmethod
    def _get_start_line(text_range: object) -> int | None:
        """Safely extract startLine from a textRange object."""
        if isinstance(text_range, Mapping):
            start_line = text_range.get("startLine")
            if isinstance(start_line, int):
                return start_line
        return None
