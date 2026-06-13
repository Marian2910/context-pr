from __future__ import annotations

from typing import Protocol

from contextpr.enrichment import IssueEnrichment
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    PullRequestFile,
    PullRequestRef,
    SonarIssue,
)


class GitHubAnalysisClient(Protocol):
    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]: ...

    def create_review(
        self,
        *,
        pull_request: PullRequestRef,
        comments: list[GitHubReviewComment],
    ) -> None: ...

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]: ...

    def delete_review_comment(self, comment_id: int) -> None: ...

    def get_authenticated_user_login(self) -> str: ...


class SonarAnalysisClient(Protocol):
    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]: ...


class IssueEnrichmentClient(Protocol):
    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None: ...

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]: ...
