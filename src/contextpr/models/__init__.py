"""Shared domain models for ContextPR."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["IssueLocation", "PullRequestRef", "SonarIssue"]


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    """Identify a pull request in a GitHub repository."""

    repository: str
    number: int


@dataclass(frozen=True, slots=True)
class IssueLocation:
    """Represent a source location for a static analysis finding."""

    path: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class SonarIssue:
    """Represent a SonarQube issue that may later map to a PR comment."""

    key: str
    rule: str
    severity: str
    message: str
    location: IssueLocation
