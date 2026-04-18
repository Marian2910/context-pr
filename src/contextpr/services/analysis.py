from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contextpr.enrichment import IssueEnrichment
from contextpr.models import (
    ExistingReviewComment,
    GitHubReviewComment,
    PullRequestFile,
    PullRequestRef,
    SonarIssue,
)

COMMENT_MARKER_PREFIX = "<!-- contextpr:issue="


@dataclass(frozen=True, slots=True)
class AnalysisResult:

    pull_request: PullRequestRef
    fetched_issues: int
    eligible_issues: int
    deleted_comments: int
    posted_comments: int
    dry_run: bool


class GitHubAnalysisClient(Protocol):

    def get_pull_request_files(self, pull_request: PullRequestRef) -> list[PullRequestFile]:
        ...

    def create_review(
        self,
        *,
        pull_request: PullRequestRef,
        comments: list[GitHubReviewComment],
    ) -> None:
        ...

    def list_existing_review_comments(
        self,
        pull_request: PullRequestRef,
    ) -> list[ExistingReviewComment]:
        ...

    def delete_review_comment(self, comment_id: int) -> None:
        ...

    def get_authenticated_user_login(self) -> str:
        ...


class SonarAnalysisClient(Protocol):

    def fetch_pull_request_issues(self, pull_request_number: int) -> list[SonarIssue]:
        ...

class IssueEnrichmentClient(Protocol):

    def enrich(self, issue: SonarIssue) -> IssueEnrichment | None:
        ...

class AnalysisService:

    def __init__(
        self,
        github_client: GitHubAnalysisClient,
        sonar_client: SonarAnalysisClient,
        issue_enricher: IssueEnrichmentClient | None = None,
    ) -> None:
        self._github_client = github_client
        self._sonar_client = sonar_client
        self._issue_enricher = issue_enricher

    def analyze_pull_request(
        self,
        *,
        pull_request: PullRequestRef,
        dry_run: bool,
    ) -> AnalysisResult:
        pull_request_files = self._github_client.get_pull_request_files(pull_request)
        changed_lines_by_file = {
            pr_file.path: self._extract_added_lines(pr_file.patch)
            for pr_file in pull_request_files
        }
        issues = self._sonar_client.fetch_pull_request_issues(pull_request.number)
        comments = [
            comment
            for issue in issues
            if (
                comment := self._issue_to_comment(
                    issue,
                    changed_lines=changed_lines_by_file.get(issue.location.path, set()),
                    enrichment=(
                        self._issue_enricher.enrich(issue)
                        if self._issue_enricher is not None
                        else None
                    ),
                )
            )
            is not None
        ]

        deleted_comments = 0
        if not dry_run:
            deleted_comments = self._delete_previous_contextpr_comments(pull_request)

        if comments and not dry_run:
            self._github_client.create_review(pull_request=pull_request, comments=comments)

        return AnalysisResult(
            pull_request=pull_request,
            fetched_issues=len(issues),
            eligible_issues=len(comments),
            deleted_comments=deleted_comments,
            posted_comments=0 if dry_run else len(comments),
            dry_run=dry_run,
        )

    @staticmethod
    def _issue_to_comment(
        issue: SonarIssue,
        changed_lines: set[int],
        enrichment: IssueEnrichment | None,
    ) -> GitHubReviewComment | None:
        line = issue.location.line
        if line is None or line not in changed_lines:
            return None

        return GitHubReviewComment(
            path=issue.location.path,
            line=line,
            body=AnalysisService._build_comment_body(issue, enrichment),
        )

    @staticmethod
    def _build_comment_body(
        issue: SonarIssue,
        enrichment: IssueEnrichment | None,
    ) -> str:
        sections = [
            f"Sonar reported a `{issue.severity}` issue (`{issue.rule}`):",
            issue.message,
        ]
        if enrichment is not None:
            sections.extend(AnalysisService._enrichment_blocks(enrichment))

        sections.append(f"{COMMENT_MARKER_PREFIX}{issue.key} -->")
        return "\n\n".join(sections)

    @staticmethod
    def _enrichment_blocks(enrichment: IssueEnrichment) -> list[str]:
        blocks = [
            enrichment.guidance.summary,
            enrichment.guidance.explanation,
            enrichment.guidance.next_step,
        ]
        if enrichment.guidance.evidence_note is not None:
            blocks.append(enrichment.guidance.evidence_note)
        return blocks

    def _delete_previous_contextpr_comments(self, pull_request: PullRequestRef) -> int:
        author_login = self._github_client.get_authenticated_user_login()
        existing_comments = self._github_client.list_existing_review_comments(pull_request)
        managed_comments = [
            comment
            for comment in existing_comments
            if comment.author_login == author_login and COMMENT_MARKER_PREFIX in comment.body
        ]

        for comment in managed_comments:
            self._github_client.delete_review_comment(comment.comment_id)

        return len(managed_comments)

    @staticmethod
    def _extract_added_lines(patch: str | None) -> set[int]:
        if not patch:
            return set()

        added_lines: set[int] = set()
        current_new_line = 0
        in_hunk = False

        for raw_line in patch.splitlines():
            if raw_line.startswith("@@"):
                parsed_line = AnalysisService._parse_hunk_new_start(raw_line)
                if parsed_line is None:
                    in_hunk = False
                    continue

                current_new_line = parsed_line
                in_hunk = True
                continue

            if not in_hunk:
                continue

            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                added_lines.add(current_new_line)
                current_new_line += 1
            elif raw_line.startswith("-") and not raw_line.startswith("---"):
                continue
            else:
                current_new_line += 1

        return added_lines

    @staticmethod
    def _parse_hunk_new_start(header: str) -> int | None:
        parts = header.split()
        if len(parts) < 3:
            return None

        new_part = parts[2]
        if not new_part.startswith("+"):
            return None

        start_text = new_part[1:].split(",", maxsplit=1)[0]
        try:
            return int(start_text)
        except ValueError:
            return None
