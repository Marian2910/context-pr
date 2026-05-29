from contextpr.enrichment import DeterministicGuidanceMessageService, HistoricalContext
from contextpr.enrichment.history import HistoricalFixReference
from contextpr.models import IssueLocation, SonarIssue


def test_message_service_builds_generic_behavior_sensitive_cleanup_guidance() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="loop-capture",
        rule="python:S1515",
        severity="MAJOR",
        message="Lambda captures loop variable",
        location=IssueLocation(path="src/app.py", line=12),
        issue_type="BUG",
    )

    explanation = service.build_explanation(issue, None, None, None)
    next_step = service.build_next_step("behavior_sensitive_cleanup", None, None, None)

    assert "prefix" not in explanation
    assert explanation == "Lambda captures loop variable."
    assert next_step is not None
    assert "prefix" not in next_step
    assert next_step == "Review the surrounding code before changing it."


def test_message_service_builds_bug_guidance_without_history() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="bug-1",
        rule="python:S9999",
        severity="CRITICAL",
        message="Possible broken logic path",
        location=IssueLocation(path="src/app.py", line=21),
        issue_type="BUG",
    )

    explanation = service.build_explanation(issue, None, None, None)
    next_step = service.build_next_step("behavior_risk", None, None, None)

    assert explanation == "Possible broken logic path."
    assert next_step is not None
    assert next_step == "Review the surrounding code before changing it."


def test_message_service_normalizes_code_smell_message() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="smell-1",
        rule="python:S7777",
        severity="MAJOR",
        message="  Refactor   this helper for readability  ",
        location=IssueLocation(path="src/app.py", line=8),
        issue_type="CODE_SMELL",
    )

    explanation = service.build_explanation(issue, None, None, None)
    next_step = service.build_next_step("cleanup_candidate", None, None, None)

    assert explanation == "Refactor this helper for readability."
    assert next_step is None


def test_message_service_uses_history_for_non_smell_non_bug_next_step() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        same_exact_path_matches=3,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
    )
    issue = SonarIssue(
        key="vuln-1",
        rule="python:S8888",
        severity="HIGH",
        message="Review this maintainability warning",
        location=IssueLocation(path="src/app.py", line=8),
        issue_type="VULNERABILITY",
    )

    next_step = service.build_next_step("general_review", None, context, "local_sonar")

    assert next_step is not None
    assert "small, local fix" in next_step.lower()
    assert "follow-up" in next_step.lower()


def test_message_service_builds_local_persistent_debt_evidence() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        same_exact_path_matches=3,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
        dominant_disposition="persistent",
        dominant_disposition_share=0.6667,
        disposition_distribution=(("persistent", 4), ("resolved", 2)),
    )

    note = service.build_evidence_note(context, "local_sonar")

    assert note is not None
    assert "this rule has already appeared multiple times in this file and was often left open" in note
    assert "may not be worth forcing in this PR unless you're already changing the surrounding code" in note


def test_message_service_marks_dataset_history_as_cross_repo() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=4,
        same_scope_matches=6,
        same_path_family_matches=6,
        same_exact_path_matches=3,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
        resolved_share=0.5,
    )

    note = service.build_evidence_note(context, "global_dataset")

    assert note is not None
    assert "In similar issues from other repositories" in note
    assert "In this repository" not in note
    assert "similar files" in note


def test_message_service_builds_local_persistent_debt_evidence_with_fix_reference() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        same_exact_path_matches=3,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
        dominant_disposition="persistent",
        dominant_disposition_share=0.6667,
        disposition_distribution=(("persistent", 4), ("resolved", 2)),
        fix_references=(
            HistoricalFixReference(
                pr_number=9,
                pr_title="Historical sonar fix seed",
                pr_url="https://github.com/marian2910/httpie/pull/9",
                file_url="https://github.com/marian2910/httpie/pull/9/files",
                file_path="httpie/internal/sonar_history_examples.py",
                resolved_at="2026-03-20T20:36:14Z",
                confidence=0.7,
                evidence=(
                    "same Sonar rule `python:S1192`",
                    "same file `httpie/internal/sonar_history_examples.py`",
                ),
            ),
        ),
    )

    note = service.build_evidence_note(context, "local_sonar")

    assert note is not None
    assert "this rule has already appeared multiple times in this file and was often left open" in note
    assert "may not be worth forcing in this PR unless you're already changing the surrounding code" in note
    assert "A similar fixed case is linked to [PR #9]" in note
    assert "Why this match is shown:" in note
    assert "- same Sonar rule `python:S1192`" in note
    assert "- same file `httpie/internal/sonar_history_examples.py`" in note
    assert "Previous fix:" in note
    assert "https://github.com/marian2910/httpie/pull/9/files" in note

def test_message_service_keeps_caution_when_behavior_history_is_exemplar_only() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="loop-capture-exemplar",
        rule="python:S1515",
        severity="MAJOR",
        message="Lambda captures loop variable",
        location=IssueLocation(path="src/app.py", line=12),
        issue_type="CODE_SMELL",
    )
    context = HistoricalContext(
        sample_size=1,
        same_rule_matches=1,
        same_scope_matches=1,
        same_path_family_matches=1,
        strong_match_count=1,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=1.0,
        maintenance_distribution=(("cleanup", 1),),
        fix_references=(
            HistoricalFixReference(
                pr_number=123,
                pr_title="Example historical fix",
                pr_url="https://github.com/org/repo/pull/123",
                file_url="https://github.com/org/repo/pull/123/files",
                confidence=0.84,
                evidence=("same Sonar rule",),
                file_path="src/app.py",
                resolved_at="2026-05-20T10:00:00Z",
            ),
        ),
    )

    note = service.build_evidence_note(
        issue,
        "inspect_before_changing",
        None,
        context,
        "local_sonar",
    )

    assert note is not None
    assert "Review the surrounding code before changing it." in note
    assert "A similar fixed case is linked to [PR #123](https://github.com/org/repo/pull/123)" in note


def test_message_service_distinguishes_recurrence_with_some_past_resolutions() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="recurring-addressed",
        rule="python:S3923",
        severity="MAJOR",
        message="Remove this if statement or edit its code blocks so that they're not all the same.",
        location=IssueLocation(path="src/app.py", line=14),
        issue_type="CODE_SMELL",
    )
    context = HistoricalContext(
        sample_size=4,
        same_rule_matches=4,
        same_scope_matches=4,
        same_path_family_matches=4,
        same_exact_path_matches=2,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.5,
        maintenance_distribution=(("cleanup", 2), ("behavior", 2)),
        resolved_share=0.5,
    )

    note = service.build_evidence_note(
        issue,
        "recurs_here",
        None,
        context,
        "local_sonar",
    )

    assert note is not None
    assert "appeared multiple times in this file before, and some past cases were addressed" in note
    assert "repeated local issue" in note.lower()


def test_message_service_distinguishes_recurrence_without_past_fix_evidence() -> None:
    service = DeterministicGuidanceMessageService()
    issue = SonarIssue(
        key="recurring-unresolved",
        rule="python:S3923",
        severity="MAJOR",
        message="Remove this if statement or edit its code blocks so that they're not all the same.",
        location=IssueLocation(path="src/app.py", line=14),
        issue_type="CODE_SMELL",
    )
    context = HistoricalContext(
        sample_size=4,
        same_rule_matches=4,
        same_scope_matches=4,
        same_path_family_matches=4,
        same_exact_path_matches=2,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.5,
        maintenance_distribution=(("cleanup", 2), ("behavior", 2)),
        resolved_share=0.0,
    )

    note = service.build_evidence_note(
        issue,
        "recurs_here",
        None,
        context,
        "local_sonar",
    )

    assert note is not None
    assert "this issue has appeared multiple times in this file before but was not addressed" in note.lower()
    assert "repeated local issue" in note.lower()


def test_message_service_returns_none_without_context() -> None:
    service = DeterministicGuidanceMessageService()

    assert service.build_evidence_note(None, None) is None
    assert service.is_split_distribution((("cleanup", 1),), sample_size=1) is False


def test_message_service_reports_recurring_maintenance_focus() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=2,
        strong_match_count=4,
        dominant_maintenance="supporting",
        dominant_maintenance_share=0.4,
        maintenance_distribution=(("supporting", 2), ("cleanup", 2), ("behavior", 2)),
    )

    assert service.maintainability_focus(context) == "recurring_maintenance"
