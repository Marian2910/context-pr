from __future__ import annotations

from dataclasses import dataclass
import re

from contextpr.enrichment import IssueEnrichment
from contextpr.models import GitHubReviewComment, SonarIssue

COMMENT_MARKER_PREFIX = "<!-- contextpr:issue="
TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class CommentDraft:
    issue: SonarIssue
    enrichment: IssueEnrichment | None
    start_line: int | None
    end_line: int


class ReviewCommentComposer:
    def issue_to_draft(
        self,
        issue: SonarIssue,
        changed_lines: set[int],
        enrichment: IssueEnrichment | None,
    ) -> CommentDraft | None:
        line = issue.location.line
        if line is None or line not in changed_lines:
            return None

        start_line = self.comment_start_line(issue, changed_lines)
        end_line = (
            issue.location.end_line
            if start_line is not None and issue.location.end_line is not None
            else line
        )
        return CommentDraft(
            issue=issue,
            enrichment=enrichment,
            start_line=start_line,
            end_line=end_line,
        )

    def drafts_to_comments(self, drafts: list[CommentDraft]) -> list[GitHubReviewComment]:
        comments: list[GitHubReviewComment] = []
        seen_signatures: dict[str, str] = {}
        for draft in drafts:
            signature = self.duplicate_signature(draft.issue, draft.enrichment)
            body = self.build_comment_body(
                draft.issue,
                draft.enrichment,
                duplicate_reference=seen_signatures.get(signature),
            )
            comments.append(
                GitHubReviewComment(
                    path=draft.issue.location.path,
                    line=draft.end_line,
                    body=body,
                    start_line=draft.start_line,
                    start_side="RIGHT" if draft.start_line is not None else None,
                )
            )
            seen_signatures.setdefault(signature, self.issue_reference(draft.issue))
        return comments

    @staticmethod
    def comment_start_line(issue: SonarIssue, changed_lines: set[int]) -> int | None:
        start_line = issue.location.line
        end_line = issue.location.end_line
        if start_line is None or end_line is None or end_line <= start_line:
            return None

        issue_lines = set(range(start_line, end_line + 1))
        if issue_lines.issubset(changed_lines):
            return start_line

        return None

    def build_comment_body(
        self,
        issue: SonarIssue,
        enrichment: IssueEnrichment | None,
        *,
        duplicate_reference: str | None = None,
    ) -> str:
        note = self.reviewer_note(
            issue,
            enrichment,
            duplicate_reference=duplicate_reference,
        )
        return "\n\n".join((note, f"{COMMENT_MARKER_PREFIX}{issue.key} -->"))

    def reviewer_note(
        self,
        issue: SonarIssue,
        enrichment: IssueEnrichment | None,
        *,
        duplicate_reference: str | None = None,
    ) -> str:
        if enrichment is None:
            return issue.message

        guidance = enrichment.guidance
        if guidance.level is guidance.level.MINIMAL:
            sections = [issue.message]
            if guidance.evidence_note is not None:
                sections.append(guidance.evidence_note)
            return " ".join(sections)

        if duplicate_reference is not None:
            return f"Same as in [{duplicate_reference}]."

        sections = self.deduplicated_sections(
            self.issue_anchor(issue, guidance.level),
            guidance.explanation,
            guidance.next_step,
            guidance.evidence_note,
        )
        return " ".join(sections[:2]) if sections else issue.message

    @staticmethod
    def issue_anchor(issue: SonarIssue, guidance_level: object) -> str | None:
        if issue.issue_type == "CODE_SMELL" and str(guidance_level) != "minimal":
            return ReviewCommentComposer.normalize_sentence(issue.message)
        return None

    def deduplicated_sections(self, *sections: str | None) -> list[str]:
        kept_sections: list[str] = []
        for section in sections:
            if section is None:
                continue
            normalized = section.strip()
            if not normalized:
                continue
            if any(self.sections_overlap(normalized, existing) for existing in kept_sections):
                continue
            kept_sections.append(normalized)
        return kept_sections

    def duplicate_signature(
        self,
        issue: SonarIssue,
        enrichment: IssueEnrichment | None,
    ) -> str:
        if enrichment is None:
            return f"{issue.rule}|{self.normalize_section(issue.message)}"

        guidance = enrichment.guidance
        normalized_parts = [
            issue.rule,
            guidance.level.value,
            self.normalize_section(guidance.explanation),
            self.normalize_section(guidance.next_step),
            self.normalize_section(guidance.evidence_note),
        ]
        return "|".join(normalized_parts)

    @staticmethod
    def issue_reference(issue: SonarIssue) -> str:
        if issue.location.line is None:
            return issue.location.path
        return f"{issue.location.path}:{issue.location.line}"

    @staticmethod
    def normalize_sentence(text: str) -> str:
        normalized = " ".join(text.strip().split())
        if not normalized:
            return text
        if normalized[-1] not in ".!?":
            normalized = f"{normalized}."
        return normalized

    @staticmethod
    def normalize_section(section: str | None) -> str:
        if section is None:
            return ""
        return " ".join(section.strip().lower().split())

    @staticmethod
    def sections_overlap(left: str, right: str) -> bool:
        left_tokens = set(TOKEN_PATTERN.findall(left.lower()))
        right_tokens = set(TOKEN_PATTERN.findall(right.lower()))
        if not left_tokens or not right_tokens:
            return False

        overlap = len(left_tokens & right_tokens)
        smaller_size = min(len(left_tokens), len(right_tokens))
        return overlap / smaller_size >= 0.6
