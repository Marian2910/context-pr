"""SonarQube and SonarCloud integration placeholders."""

from __future__ import annotations

from contextpr.config import Settings
from contextpr.models import SonarIssue


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
        raise NotImplementedError("SonarQube issue retrieval is not implemented yet.")

    def fetch_quality_gate_status(self, pull_request_number: int) -> str:
        """Fetch the quality gate status for a pull request analysis."""
        raise NotImplementedError("SonarQube quality gate retrieval is not implemented yet.")
