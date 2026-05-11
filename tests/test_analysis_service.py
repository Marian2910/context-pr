from contextpr.enrichment import (
    DeveloperGuidance,
    GuidanceLevel,
    HistoricalContext,
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

<<<<<<< HEAD

=======
>>>>>>> origin/main
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
                location=IssueLocation(path="src/app.py", line=11, end_line=12),
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
                level=GuidanceLevel.DETAILED,
                explanation="This is probably safe to simplify if the current structure is not intentional.",
                next_step=(
                    "Before simplifying the conditional, verify that the repeated "
                    "branches are not intentionally preserving behavior or readability."
                ),
                evidence_note=(
<<<<<<< HEAD
                    "Historically similar cases usually disappeared during later "
=======
                    "In a small set of similar cases, developers leaned toward "
>>>>>>> origin/main
                    "small refactors."
                ),
            ),
            historical_context=HistoricalContext(
                sample_size=6,
                same_rule_matches=3,
                same_scope_matches=6,
                same_path_family_matches=6,
                strong_match_count=4,
                dominant_maintenance="cleanup",
                dominant_maintenance_share=0.6667,
                maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
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
    assert comments[0].start_line == 11
    assert comments[0].line == 12
    assert "Sonar reported" not in comments[0].body
    assert "This is probably safe to simplify if the current structure is not intentional." in comments[0].body
    assert "Before simplifying the conditional, verify that the repeated branches are not intentionally preserving behavior or readability." in comments[0].body
<<<<<<< HEAD
    assert "Historically similar cases usually disappeared during later small refactors." in comments[0].body
=======
    assert "In a small set of similar cases, developers leaned toward small refactors." in comments[0].body
>>>>>>> origin/main
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


def test_issue_to_comment_falls_back_to_single_line_when_range_is_not_fully_added() -> None:
    comment = AnalysisService._issue_to_comment(
        SonarIssue(
            key="issue-range",
            rule="python:S3923",
            severity="MAJOR",
            message="Repeated branches",
            location=IssueLocation(path="src/app.py", line=11, end_line=13),
        ),
        changed_lines={11, 12},
        enrichment=None,
    )

    assert comment is not None
    assert comment.start_line is None
    assert comment.line == 11


def test_extract_added_lines_handles_multiple_hunks_and_deletions() -> None:
    patch = (
        "@@ -1,3 +1,4 @@\n"
        " context\n"
        "-old\n"
        "+new\n"
        " same\n"
        "+extra\n"
        "@@ -10,2 +20,3 @@\n"
        "+later\n"
        " unchanged\n"
    )

    assert AnalysisService._extract_added_lines(patch) == {2, 4, 20}


def test_extract_added_lines_returns_empty_set_for_invalid_patch() -> None:
    assert AnalysisService._extract_added_lines(None) == set()
    assert AnalysisService._extract_added_lines("not a hunk") == set()


def test_reviewer_note_handles_minimal_and_single_sentence_guidance() -> None:
    minimal_note = AnalysisService._reviewer_note(
        SonarIssue(
            key="issue-minimal",
            rule="python:S1481",
            severity="MINOR",
            message='Remove the unused local variable "name".',
            location=IssueLocation(path="src/app.py", line=11),
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.MINIMAL,
<<<<<<< HEAD
                evidence_note="Historically similar cases usually disappeared during later small refactors.",
            ),
=======
                evidence_note="Similar cases here were often small refactors.",
            ),
            intent_prediction=None,
>>>>>>> origin/main
            historical_context=None,
        ),
    )
    single_sentence_note = AnalysisService._reviewer_note(
        SonarIssue(
            key="issue-detailed",
            rule="python:S1515",
            severity="MAJOR",
            message="Loop variable capture",
            location=IssueLocation(path="src/app.py", line=20),
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.DETAILED,
                explanation="Capture `prefix` when the lambda is created.",
            ),
<<<<<<< HEAD
=======
            intent_prediction=None,
>>>>>>> origin/main
            historical_context=None,
        ),
    )

    assert minimal_note == (
        'Remove the unused local variable "name". '
<<<<<<< HEAD
        "Historically similar cases usually disappeared during later small refactors."
=======
        "Similar cases here were often small refactors."
>>>>>>> origin/main
    )
    assert single_sentence_note == "Capture `prefix` when the lambda is created."


def test_comment_start_line_and_hunk_parser_handle_invalid_ranges() -> None:
    assert AnalysisService._comment_start_line(
        SonarIssue(
            key="issue-range-none",
            rule="python:S100",
            severity="MAJOR",
            message="Invalid range",
            location=IssueLocation(path="src/app.py", line=10, end_line=10),
        ),
        changed_lines={10},
    ) is None
    assert AnalysisService._parse_hunk_new_start("@@ invalid @@") is None
    assert AnalysisService._parse_hunk_new_start("@@ -1,2 -3,4 @@") is None
