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

    repository: str
    number: int


@dataclass(frozen=True, slots=True)
class IssueLocation:

    path: str
    line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class SonarIssue:

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

    path: str
    status: str
    patch: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubReviewComment:

    path: str
    line: int
    body: str
    side: str = "RIGHT"
    start_line: int | None = None
    start_side: str | None = None


@dataclass(frozen=True, slots=True)
class ExistingReviewComment:

    comment_id: int
    path: str
    line: int | None
    body: str
    author_login: str
