from contextpr.enrichment import (
    DeveloperGuidance,
    HistoricalContext,
    IntentPrediction,
    IssueEnrichment,
)
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    IssueLocation,
    PullRequestFile,
    PullRequestRef,
    SonarIssue,
)
from contextpr.services import AnalysisService

EXPLANATION_OPTIONS = (
    "This looks like a cleanup issue rather than a functional change.",
    "This seems more like code cleanup than a behavior fix.",
    "This warning points more toward simplification than a change in behavior.",
    "This looks like something to clean up rather than a functional defect.",
)

EVIDENCE_OPTIONS = (
    "Similar cases were usually resolved with cleanup around the flagged code.",
    "In similar cases, developers usually handled this as a cleanup task.",
    "Historically, issues like this were more often addressed by simplifying nearby code.",
    "Looking at similar cases, this was usually handled as cleanup rather than a larger change.",
)


class FakeGitHubClient:

    def __init__(self) -> None:
        """Initialize the fake client state."""
        self.created_reviews: list[tuple[PullRequestRef, list[GitHubReviewComment]]] = []
        self.deleted_comment_ids: list[int] = []

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
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
        self.created_reviews.append((pull_request, comments))

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]:
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
        self.deleted_comment_ids.append(comment_id)

    def get_authenticated_user_login(self) -> str:
        return "contextpr-bot"


class FakeSonarClient:

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
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


class FakeIssueEnricher:

    def enrich(self, issue: SonarIssue) -> IssueEnrichment:
        return IssueEnrichment(
            guidance=DeveloperGuidance(
                summary=(
                    "Sonar flagged this because all branches of the condition appear "
                    "to do the same thing."
                ),
                explanation="This looks like a cleanup issue rather than a functional change.",
                next_step=(
                    "A good next step is to simplify the condition or remove duplicated "
                    "branches if they are truly equivalent."
                ),
                evidence_note=(
                    "Similar cases were usually resolved with cleanup around the "
                    "flagged code."
                ),
            ),
            intent_prediction=IntentPrediction(label="refactor", confidence=0.82),
            historical_context=HistoricalContext(
                sample_size=6,
                label_distribution=(("refactor", 4), ("fix", 2)),
                same_rule_matches=3,
            ),
        )


def test_analyze_pull_request_posts_only_eligible_comments() -> None:
    github_client = FakeGitHubClient()
    service = AnalysisService(
        github_client=github_client,
        sonar_client=FakeSonarClient(),
        issue_enricher=FakeIssueEnricher(),
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
    assert "Sonar reported a `MAJOR` issue (`python:S100`):" in comments[0].body
    assert "First issue" in comments[0].body
    assert any(option in comments[0].body for option in EXPLANATION_OPTIONS)
    assert any(option in comments[0].body for option in EVIDENCE_OPTIONS)
    assert "Likely remediation intent" not in comments[0].body
    assert "Historical pattern:" not in comments[0].body
    assert github_client.deleted_comment_ids == [99]


def test_analyze_pull_request_skips_publish_on_dry_run() -> None:
    github_client = FakeGitHubClient()
    service = AnalysisService(
        github_client=github_client,
        sonar_client=FakeSonarClient(),
        issue_enricher=FakeIssueEnricher(),
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
