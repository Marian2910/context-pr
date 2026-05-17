from contextpr.enrichment import DeterministicGuidanceMessageService, HistoricalContext
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

    explanation = service.build_explanation(issue, "behavior_sensitive_cleanup", None, None)
    next_step = service.build_next_step(issue, "behavior_sensitive_cleanup", None, None)

    assert "prefix" not in explanation
    assert "behavior" in explanation.lower() or "state" in explanation.lower()
    assert next_step is not None
    assert "prefix" not in next_step
    assert "behavior" in next_step.lower() or "state" in next_step.lower()


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

    explanation = service.build_explanation(issue, "behavior_risk", None, None)
    next_step = service.build_next_step(issue, "behavior_risk", None, None)

    assert "behavior" in explanation.lower() or "runtime" in explanation.lower()
    assert next_step is not None
    assert "logic" in next_step.lower() or "behavior" in next_step.lower()


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

    explanation = service.build_explanation(issue, "cleanup_candidate", None, None)
    next_step = service.build_next_step(issue, "cleanup_candidate", None, None)

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

    next_step = service.build_next_step(issue, "general_review", context, "local_sonar")

    assert next_step is not None
    assert "cleanup" in next_step.lower() or "open" in next_step.lower()


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
    assert "Similar local cases" in note
    assert "leave it for follow-up" in note or "fix it now" in note


def test_message_service_builds_global_split_distribution_evidence() -> None:
    service = DeterministicGuidanceMessageService()
    context = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        same_exact_path_matches=2,
        strong_match_count=4,
        dominant_maintenance="behavior",
        dominant_maintenance_share=0.5,
        maintenance_distribution=(("behavior", 3), ("cleanup", 2), ("supporting", 1)),
    )

    note = service.build_evidence_note(context, "global_dataset")

    assert note is not None
    assert "Historically similar matches" in note
    assert "split between" in note


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
