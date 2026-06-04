from contextpr.enrichment import EvidenceBackedGuidance, HistoricalCaseType
from contextpr.enrichment.nlp import DeveloperGuidance, GuidanceLevel, IssueEnrichment
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    IssueLocation,
    PullRequestFile,
    PullRequestRef,
    SonarIssue,
)
from contextpr.services import AnalysisService, ReviewCommentComposer


class FakeGitHubClient:
    def __init__(self) -> None:
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
                issue_type="CODE_SMELL",
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
        return _enrichment(case_key=issue.key)

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]:
        return {issue.key: self.enrich(issue) for issue in issues}


class FakeBatchIssueEnricher(FakeIssueEnricher):
    def __init__(self) -> None:
        self.enrich_calls: list[str] = []
        self.enrich_many_calls: list[list[str]] = []

    def enrich(self, issue: SonarIssue) -> IssueEnrichment:
        self.enrich_calls.append(issue.key)
        return super().enrich(issue)

    def enrich_many(self, issues: list[SonarIssue]) -> dict[str, IssueEnrichment | None]:
        self.enrich_many_calls.append([issue.key for issue in issues])
        return {issue.key: FakeIssueEnricher.enrich(self, issue) for issue in issues}


def test_analyze_pull_request_posts_compact_evidence_comment() -> None:
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
    comments = github_client.created_reviews[0][1]
    assert len(comments) == 1
    assert comments[0].start_line == 11
    assert comments[0].line == 12
    assert "First issue." in comments[0].body
    assert "ContextPR: likely worth fixing now · 86% confidence" in comments[0].body
    assert "Closest precedent:" in comments[0].body
    assert "appeared multiple times" not in comments[0].body
    assert github_client.deleted_comment_ids == [99]


def test_analyze_pull_request_uses_batch_enrichment() -> None:
    github_client = FakeGitHubClient()
    issue_enricher = FakeBatchIssueEnricher()
    service = AnalysisService(
        github_client=github_client,
        sonar_client=FakeSonarClient(),
        issue_enricher=issue_enricher,
    )

    service.analyze_pull_request(
        pull_request=PullRequestRef(repository="octo/example", number=7),
        dry_run=True,
    )

    assert issue_enricher.enrich_many_calls == [["issue-1", "issue-2", "issue-3"]]
    assert issue_enricher.enrich_calls == []


def test_drafts_to_comments_skips_repeated_guidance() -> None:
    first_issue = SonarIssue(
        key="issue-1",
        rule="python:S100",
        severity="MAJOR",
        message="First issue",
        location=IssueLocation(path="src/app.py", line=11),
        issue_type="CODE_SMELL",
    )
    second_issue = SonarIssue(
        key="issue-2",
        rule="python:S100",
        severity="MAJOR",
        message="Second issue",
        location=IssueLocation(path="src/app.py", line=12),
        issue_type="CODE_SMELL",
    )
    composer = ReviewCommentComposer()
    first_draft = composer.issue_to_draft(
        first_issue,
        {11, 12},
        _enrichment(case_key="same-case"),
    )
    second_draft = composer.issue_to_draft(
        second_issue,
        {11, 12},
        _enrichment(case_key="same-case"),
    )
    assert first_draft is not None
    assert second_draft is not None

    comments = composer.drafts_to_comments([first_draft, second_draft])

    assert len(comments) == 1
    assert comments[0].line == 11


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


def test_issue_to_draft_falls_back_to_single_line_when_range_is_not_fully_added() -> None:
    comment = ReviewCommentComposer().issue_to_draft(
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
    assert comment.end_line == 11


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


def _enrichment(case_key: str) -> IssueEnrichment:
    return IssueEnrichment(
        guidance=DeveloperGuidance(
            level=GuidanceLevel.CONTEXTUAL,
            evidence=EvidenceBackedGuidance(
                decision="likely worth fixing now",
                confidence=0.86,
                reason="4 of 5 close historical matches for `python:S100` were fixed.",
                case_type=HistoricalCaseType.PREVIOUS_FIX,
                case_key=case_key,
                precedent_url="https://github.com/org/repo/pull/9/files",
            ),
        ),
        historical_context=None,
    )
