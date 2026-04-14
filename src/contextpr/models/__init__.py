from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ExistingReviewComment",
    "GitHubReviewComment",
    "IssueLocation",
    "PullRequestRef",
    "PullRequestFile",
    "SonarIssue",
]


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
    issue_type: str = ""
    tags: tuple[str, ...] = ()
    clean_code_attribute: str = ""
    clean_code_attribute_category: str = ""


@dataclass(frozen=True, slots=True)
class PullRequestFile:
    """Represent a file that changed in a pull request."""

    path: str
    status: str
    patch: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubReviewComment:
    """Represent a GitHub inline review comment payload."""

    path: str
    line: int
    body: str
    side: str = "RIGHT"


@dataclass(frozen=True, slots=True)
class ExistingReviewComment:
    """Represent an existing inline review comment already on the pull request."""

    comment_id: int
    path: str
    line: int | None
    body: str
    author_login: str
