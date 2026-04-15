"""Tests for the analysis orchestration service."""

from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    IssueLocation,
    PullRequestFile,
    PullRequestRef,
    SonarIssue,
)
from contextpr.services import AnalysisService


class FakeGitHubClient:
    """Simple fake GitHub client for service tests."""

    def __init__(self) -> None:
        """Initialize the fake client state."""
        self.created_reviews: list[tuple[PullRequestRef, list[GitHubReviewComment]]] = []
        self.deleted_comment_ids: list[int] = []

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
        """Return deterministic changed files."""
        return [
            PullRequestFile(
                path="src/app.py",
                status="modified",
                patch="@@ -10,2 +10,3 @@\n context\n-old\n+new\n+another\n",
            ),
            PullRequestFile(path="src/other.py", status="modified"),
        ]

    def create_review(
        self,
        *,
        pull_request: PullRequestRef,
        comments: list[GitHubReviewComment],
    ) -> None:
        """Record created reviews for assertions."""
        self.created_reviews.append((pull_request, comments))

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]:
        """Return an existing managed comment to be cleaned up."""
        return [
            ExistingReviewComment(
                comment_id=99,
                path="src/app.py",
                line=10,
                body="Old comment\n\n<!-- contextpr:issue=old-issue -->",
                author_login="contextpr-bot",
            )
        ]

    def delete_review_comment(self, comment_id: int) -> None:
        """Record deleted review comments for assertions."""
        self.deleted_comment_ids.append(comment_id)

    def get_authenticated_user_login(self) -> str:
        """Return the login used by the fake GitHub identity."""
        return "contextpr-bot"


class FakeSonarClient:
    """Simple fake Sonar client for service tests."""

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
        """Return a mix of eligible and ineligible issues."""
        return [
            SonarIssue(
                key="issue-1",
                rule="python:S100",
                severity="MAJOR",
                message="First issue",
                location=IssueLocation(path="src/app.py", line=11),
            ),
            SonarIssue(
                key="issue-2",
                rule="python:S101",
                severity="MINOR",
                message="Missing line",
                location=IssueLocation(path="src/app.py", line=None),
            ),
            SonarIssue(
                key="issue-3",
                rule="python:S102",
                severity="CRITICAL",
                message="Not on an added diff line",
                location=IssueLocation(path="src/app.py", line=10),
            ),
        ]


def test_analyze_pull_request_posts_only_eligible_comments() -> None:
    """Only Sonar issues with path and line in the PR should be posted."""
    github_client = FakeGitHubClient()
    service = AnalysisService(
        github_client=github_client,
        sonar_client=FakeSonarClient(),
    )

    result = service.analyze_pull_request(
        pull_request=PullRequestRef(repository="octo/example", number=7),
        dry_run=False,
    )

    assert result.fetched_issues == 3
    assert result.eligible_issues == 1
    assert result.deleted_comments == 1
    assert result.posted_comments == 1
    assert len(github_client.created_reviews) == 1
    review_pull_request, comments = github_client.created_reviews[0]
    assert review_pull_request == PullRequestRef(repository="octo/example", number=7)
    assert len(comments) == 1
    assert github_client.deleted_comment_ids == [99]


def test_analyze_pull_request_skips_publish_on_dry_run() -> None:
    """Dry runs should not create GitHub reviews."""
    github_client = FakeGitHubClient()
    service = AnalysisService(
        github_client=github_client,
        sonar_client=FakeSonarClient(),
    )

    result = service.analyze_pull_request(
        pull_request=PullRequestRef(repository="octo/example", number=7),
        dry_run=True,
    )

    assert result.eligible_issues == 1
    assert result.deleted_comments == 0
    assert result.posted_comments == 0
    assert github_client.created_reviews == []
    assert github_client.deleted_comment_ids == []
