from contextpr.enrichment import (
    CombinedHistoricalContext,
    EvidenceBackedGuidance,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
)
from contextpr.enrichment.nlp import DeveloperGuidance, GuidanceLevel, IssueEnrichment
from contextpr.models import IssueLocation, SonarIssue
from contextpr.services import ReviewCommentComposer


def test_review_comment_uses_compact_evidence_format() -> None:
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1192",
            rule="python:S1192",
            severity="LOW",
            message="Define a constant instead of duplicating this literal 3 times",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                evidence=EvidenceBackedGuidance(
                    decision="likely worth fixing now",
                    confidence=0.86,
                    reason=(
                        "Repository history for `python:S1192` includes similar cases that were "
                        "fixed, including one in this file."
                    ),
                    case_type=HistoricalCaseType.PREVIOUS_FIX,
                    case_key="fixed-1",
                    precedent_url="https://github.com/org/repo/pull/9/files",
                ),
            ),
            historical_context=None,
        ),
    )

    assert note == (
        "Define a constant instead of duplicating this literal 3 times.\n\n"
        "ContextPR: likely worth fixing now · historical match score of 86% \n"
        "Reason: Repository history for `python:S1192` includes similar cases that were fixed, "
        "including one in this file."
    )
    assert "appeared multiple times" not in note
    assert "This seems worth fixing" not in note


def test_review_comment_uses_detailed_template_for_high_confidence_precedent() -> None:
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1192",
            rule="python:S1192",
            severity="LOW",
            message=(
                "Define a constant instead of duplicating this literal "
                "'ContextPR similarity baseline for historical sonar issues' 3 times"
            ),
            location=IssueLocation(path="src/app.py", line=15),
            issue_type="CODE_SMELL",
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                evidence=EvidenceBackedGuidance(
                    decision="likely worth fixing now",
                    confidence=0.94,
                    reason=(
                        "Repository history for `python:S1192` includes similar cases that were "
                        "fixed, including one in this file."
                    ),
                    case_type=HistoricalCaseType.PREVIOUS_FIX,
                    case_key="fixed-1",
                    precedent_url="https://github.com/marian2910/httpie/pull/9/files",
                    precedent_pr_number=9,
                    precedent_evidence=(
                        "same Sonar rule `python:S1192`",
                        "Sonar marked the historical issue as fixed/resolved",
                        "same file `httpie/internal/sonar_history_examples.py`",
                        "historical issue was near line 12",
                    ),
                ),
            ),
            historical_context=None,
        ),
    )

    assert note == (
        "Define a constant instead of duplicating this literal "
        "'ContextPR similarity baseline for historical sonar issues' 3 times.\n\n"
        "A similar fixed case is linked to PR #9, with a 94% historical match score from Sonar "
        "resolution history.\n\n"
        "Why this match is shown:\n\n"
        "- same Sonar rule `python:S1192`\n"
        "- Sonar marked the historical issue as fixed/resolved\n"
        "- same file `httpie/internal/sonar_history_examples.py`\n"
        "- historical issue was near line 12\n\n"
        "Previous fix:\n"
        "https://github.com/marian2910/httpie/pull/9/files"
    )


def test_review_comment_omits_precedent_when_no_link_exists() -> None:
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1066",
            rule="python:S1066",
            severity="LOW",
            message="Merge this if statement with the enclosing one.",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                evidence=EvidenceBackedGuidance(
                    decision="safe to defer",
                    confidence=0.78,
                    reason=(
                        "Repository history for `python:S1066` includes accepted or open cases."
                    ),
                    case_type=HistoricalCaseType.DEFERRED,
                    case_key="accepted-1",
                ),
            ),
            historical_context=None,
        ),
    )

    assert "ContextPR: safe to defer · historical match score of 78%" in note
    assert "Closest precedent:" not in note


def test_review_comment_omits_precedent_for_non_high_confidence_match() -> None:
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1481",
            rule="python:S1481",
            severity="LOW",
            message='Remove the unused local variable "unused_diagnostic_marker".',
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        ),
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                evidence=EvidenceBackedGuidance(
                    decision="review carefully",
                    confidence=0.79,
                    reason="the closest same-rule historical match for `python:S1481` needs extra review.",
                    case_type=HistoricalCaseType.REVIEW_CAREFULLY,
                    case_key="case-1481",
                    precedent_url="https://github.com/marian2910/httpie/pull/9/files",
                    precedent_pr_number=9,
                ),
            ),
            historical_context=None,
        ),
    )

    assert "Closest precedent:" not in note
    assert "https://github.com/marian2910/httpie/pull/9/files" not in note
    assert "closest same-rule historical match" in note


def test_review_comment_adds_disclaimer_for_dataset_fallback() -> None:
    enriched = IssueEnrichment(
        guidance=DeveloperGuidance(
            level=GuidanceLevel.CONTEXTUAL,
            evidence=EvidenceBackedGuidance(
                decision="likely worth fixing now",
                confidence=0.82,
                reason=(
                    "Cross-project dataset history for `python:S1172` includes similar cases "
                    "that were fixed."
                ),
                case_type=HistoricalCaseType.PREVIOUS_FIX,
                case_key="dataset:4",
            ),
        ),
        historical_context=CombinedHistoricalContext(
            dataset=HistoricalEvidenceSummary(
                source_name="dataset",
                cases=(),
                related_cases_count=5,
                close_cases_count=3,
                fixed_cases_count=3,
                accepted_cases_count=0,
                persistent_cases_count=0,
            )
        ),
    )
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1172",
            rule="python:S1172",
            severity="LOW",
            message="Remove unused function parameter",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        ),
        enriched,
    )

    assert "Note: this historical match score is based on similar cross-project issues." in note
    assert "Reason:" not in note


def test_dataset_reason_does_not_expose_candidate_counts() -> None:
    enriched = IssueEnrichment(
        guidance=DeveloperGuidance(
            level=GuidanceLevel.CONTEXTUAL,
            evidence=EvidenceBackedGuidance(
                decision="likely worth fixing now",
                confidence=0.82,
                reason=(
                    "Cross-project dataset history for `python:S1172` includes similar cases "
                    "that were fixed."
                ),
                case_type=HistoricalCaseType.PREVIOUS_FIX,
                case_key="dataset:9",
            ),
        ),
        historical_context=CombinedHistoricalContext(
            dataset=HistoricalEvidenceSummary(
                source_name="dataset",
                cases=(),
                related_cases_count=241,
                close_cases_count=5,
                fixed_cases_count=5,
                accepted_cases_count=0,
                persistent_cases_count=0,
            )
        ),
    )
    note = ReviewCommentComposer().reviewer_note(
        SonarIssue(
            key="issue-s1172",
            rule="python:S1172",
            severity="LOW",
            message="Remove unused function parameter",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        ),
        enriched,
    )

    assert "ContextPR: likely worth fixing now · historical match score of 82%" in note
    assert "Reason:" not in note
    assert "5 of 241" not in note
    assert "5 of 5" not in note


def test_review_comment_helpers_cover_remaining_branches() -> None:
    composer = ReviewCommentComposer()
    issue = SonarIssue(
        key="issue-s1172",
        rule="python:S1172",
        severity="LOW",
        message="Remove unused function parameter",
        location=IssueLocation(path="src/app.py", line=12),
        issue_type="CODE_SMELL",
    )

    assert composer.fallback_disclaimer(
        IssueEnrichment(
            guidance=DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                evidence=EvidenceBackedGuidance(
                    decision="likely worth fixing now",
                    confidence=0.82,
                    reason="reason",
                    case_type=HistoricalCaseType.PREVIOUS_FIX,
                    case_key="case-1",
                ),
            ),
            historical_context=CombinedHistoricalContext(),
        )
    ) is None
    assert composer.issue_anchor(issue, "minimal") is None
    assert composer.issue_anchor(
        SonarIssue(
            key="issue-bug",
            rule="python:S1515",
            severity="HIGH",
            message="Bug issue",
            location=IssueLocation(path="src/app.py", line=8),
            issue_type="BUG",
        ),
        GuidanceLevel.CONTEXTUAL,
    ) is None
