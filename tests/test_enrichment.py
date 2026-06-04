from pathlib import Path

import pytest

from contextpr.enrichment import (
    HistoricalCaseType,
    IssueEnricher,
    LocalSonarHistoryRetriever,
)
from contextpr.models import IssueLocation, SonarIssue
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    SonarIssueRecord,
)


def test_issue_enricher_requires_store_when_local_history_is_enabled() -> None:
    enricher = IssueEnricher(enable_local_history=True)

    with pytest.raises(NotImplementedError, match="configured repository store"):
        enricher.enrich(_issue())


def test_global_dataset_no_longer_creates_inline_enrichment(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "message,rule,type,tags,clean_code_attribute,clean_code_attribute_category,"
                "impacts,component,ccs_classification,creation_date",
                '"Remove unused function parameter",python:S1172,CODE_SMELL,'
                '"[\'unused\']",CLEAR,INTENTIONAL,"[]",repo:src/app.py,fix,2024-01-01',
            ]
        ),
        encoding="utf-8",
    )

    assert IssueEnricher(dataset_path=dataset_path).enrich(_issue()) is None


def test_local_sonar_fixed_case_builds_compact_guidance(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=42,
            title="Remove unused parameters",
            state="closed",
            merged_at="2026-05-14T10:00:00+00:00",
            updated_at="2026-05-14T10:30:00+00:00",
        ),
        files=(PullRequestFileRecord(pr_number=42, file_path="src/app.py"),),
    )
    for index in range(1, 5):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"fixed-{index}",
                rule="python:S1172",
                issue_type="CODE_SMELL",
                severity="LOW",
                component="src/app.py",
                message="Remove unused function parameter",
                status="CLOSED",
                resolution="FIXED",
                updated_at=f"2026-05-15T1{index}:00:00+00:00",
                line=20 + index,
            ),
        )

    enrichment = IssueEnricher(
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    evidence = enrichment.guidance.evidence
    assert evidence.decision == "likely worth fixing now"
    assert evidence.confidence >= 0.7
    assert evidence.case_type is HistoricalCaseType.PREVIOUS_FIX
    assert evidence.precedent_url == "https://github.com/octo/example/pull/42/files"
    assert evidence.precedent_pr_number == 42
    assert any("historical issue was near line" in item for item in evidence.precedent_evidence)
    assert "4 of 4 close historical matches for `python:S1172` were fixed" in evidence.reason
    assert "including one in this file" in evidence.reason


def test_local_sonar_accepted_cases_build_defer_guidance(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 4):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"accepted-{index}",
                rule="python:S1066",
                issue_type="CODE_SMELL",
                severity="LOW",
                component="src/app.py",
                message="Merge this if statement with the enclosing one.",
                status="ACCEPTED",
                resolution=None,
                updated_at=f"2026-05-15T1{index}:00:00+00:00",
                line=20 + index,
            ),
        )

    enrichment = IssueEnricher(
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(
        SonarIssue(
            key="issue-s1066",
            rule="python:S1066",
            severity="LOW",
            message="Merge this if statement with the enclosing one.",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        )
    )

    assert enrichment is not None
    evidence = enrichment.guidance.evidence
    assert evidence.decision == "safe to defer"
    assert evidence.case_type is HistoricalCaseType.DEFERRED
    assert "accepted or left open" in evidence.reason


def test_behavior_sensitive_case_builds_review_carefully_guidance(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="bug-fixed",
            rule="python:S1515",
            issue_type="BUG",
            severity="MAJOR",
            component="src/app.py",
            message="Add a parameter to the parent lambda function.",
            status="CLOSED",
            resolution="FIXED",
            updated_at="2026-05-15T10:00:00+00:00",
            line=12,
        ),
    )

    enrichment = IssueEnricher(
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(
        SonarIssue(
            key="issue-bug",
            rule="python:S1515",
            severity="MAJOR",
            message="Add a parameter to the parent lambda function.",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="BUG",
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.evidence.decision == "review carefully"
    assert enrichment.guidance.evidence.case_type is HistoricalCaseType.REVIEW_CAREFULLY


def test_weak_sonar_history_returns_no_enrichment(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="weak",
            rule="python:S9999",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="docs/readme.md",
            message="Unrelated warning",
            status="OPEN",
            updated_at="2026-05-15T10:00:00+00:00",
        ),
    )

    enrichment = IssueEnricher(
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is None


def test_git_history_alone_does_not_create_inline_enrichment(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 4):
        store.upsert_git_commit(
            "octo/example",
            GitCommitRecord(
                commit_sha=f"commit-{index}",
                authored_at=f"2026-05-1{index}T09:00:00+00:00",
                message=f"refactor: simplify handler {index}",
                classification="refactor",
            ),
            touches=(
                GitFileTouchRecord(
                    commit_sha=f"commit-{index}",
                    file_path="src/app.py",
                    module_family="src/app.py",
                ),
            ),
        )

    enrichment = IssueEnricher(
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is None


def test_local_sonar_retriever_exposes_ranked_cases(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="fixed",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            status="CLOSED",
            resolution="FIXED",
            updated_at="2026-05-15T10:00:00+00:00",
            line=12,
        ),
    )

    context = LocalSonarHistoryRetriever(store, "octo/example").find_context(_issue())

    assert context is not None
    best_case = context.best_case()
    assert best_case is not None
    assert best_case.issue_key == "fixed"


def _issue() -> SonarIssue:
    return SonarIssue(
        key="issue-1",
        rule="python:S1172",
        severity="LOW",
        message="Remove unused function parameter",
        location=IssueLocation(path="src/app.py", line=12),
        issue_type="CODE_SMELL",
        tags=("unused",),
    )
