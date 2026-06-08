from pathlib import Path

import pytest

from contextpr.enrichment import (
    CombinedHistoricalContext,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalIssueCase,
    IssueEnricher,
    LocalSonarHistoryRetriever,
)
from contextpr.enrichment.history.dataset import (
    DatasetMatch,
    _build_case,
    _classification_case_type,
    _match_score,
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


def test_dataset_builds_fallback_enrichment_when_local_history_is_missing(tmp_path: Path) -> None:
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

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(_issue())

    assert enrichment is not None
    evidence = enrichment.guidance.evidence
    assert evidence.decision == "likely worth fixing now"
    assert evidence.case_type is HistoricalCaseType.PREVIOUS_FIX
    assert enrichment.historical_context.preferred_source_name() == "dataset"
    assert "Cross-project dataset history" in evidence.reason


def test_local_history_stays_preferred_over_dataset_fallback(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "message,rule,type,tags,clean_code_attribute,clean_code_attribute_category,"
                "impacts,component,ccs_classification,creation_date",
                '"Remove unused function parameter",python:S1172,CODE_SMELL,'
                '"[\'unused\']",CLEAR,INTENTIONAL,"[]",repo:src/app.py,defer,2024-01-01',
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 4):
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
        dataset_path=dataset_path,
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    assert enrichment.historical_context.preferred_source_name() == "local_sonar"
    assert enrichment.guidance.evidence.decision == "likely worth fixing now"


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
    assert "Repository history for `python:S1172` includes similar cases that were fixed" in evidence.reason
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
    assert "includes accepted or open cases" in evidence.reason


def test_security_vulnerability_never_builds_safe_to_defer_guidance(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 4):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"accepted-security-{index}",
                rule="pythonsecurity:S2083",
                issue_type="VULNERABILITY",
                severity="HIGH",
                component="src/app.py",
                message="Change this code to not construct the path from user-controlled data.",
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
            key="issue-s2083",
            rule="pythonsecurity:S2083",
            severity="HIGH",
            message="Change this code to not construct the path from user-controlled data.",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="VULNERABILITY",
        )
    )

    assert enrichment is not None
    evidence = enrichment.guidance.evidence
    assert evidence.decision == "requires security review"
    assert "needs manual review" in evidence.reason


def test_security_rule_prefix_blocks_safe_to_defer_even_without_vulnerability_type(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "message,rule,type,tags,clean_code_attribute,clean_code_attribute_category,"
                "impacts,component,ccs_classification,creation_date",
                '"Change this code to not construct the path from user-controlled data.",'
                'pythonsecurity:S2083,CODE_SMELL,"[]",CLEAR,INTENTIONAL,'
                '"[{\'severity\': \'high\'}]",repo:src/app.py,defer,2024-01-01',
            ]
        ),
        encoding="utf-8",
    )

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(
        SonarIssue(
            key="issue-security-rule",
            rule="pythonsecurity:S2083",
            severity="HIGH",
            message="Change this code to not construct the path from user-controlled data.",
            location=IssueLocation(path="src/app.py", line=12),
            issue_type="CODE_SMELL",
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.evidence.decision == "requires security review"


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


def test_dataset_retriever_supports_multiple_classifications_and_caps_top_matches(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    rows = [
        (
            "Remove unused function parameter",
            "python:S1172",
            "CODE_SMELL",
            "['unused']",
            "CLEAR",
            "INTENTIONAL",
            "[{'severity': 'low'}]",
            f"repo:src/app_{index}.py",
            classification,
            "2024-01-01",
        )
        for index, classification in enumerate(
            ["fix", "accepted", "persistent", "manual_review", "true_positive", "unknown"],
            start=1,
        )
    ]
    dataset_path.write_text(
        "\n".join(
            [
                "message,rule,type,tags,clean_code_attribute,clean_code_attribute_category,"
                "impacts,component,ccs_classification,creation_date",
                *[
                    ",".join(f'"{value}"' for value in row)
                    for row in rows
                ],
            ]
        ),
        encoding="utf-8",
    )

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(_issue())

    assert enrichment is not None
    dataset_summary = enrichment.historical_context.dataset
    assert dataset_summary is not None
    assert dataset_summary.close_cases_count == 5
    assert dataset_summary.related_cases_count == 5
    assert dataset_summary.fixed_cases_count == 2
    assert dataset_summary.accepted_cases_count == 1
    assert dataset_summary.persistent_cases_count == 1
    assert any(case.case_type is HistoricalCaseType.REVIEW_CAREFULLY for case in dataset_summary.cases)


def test_dataset_fallback_returns_none_for_weak_or_unmapped_matches(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "message,rule,type,tags,clean_code_attribute,clean_code_attribute_category,"
                "impacts,component,ccs_classification,creation_date",
                '"Totally unrelated issue",python:S9999,BUG,"[]",ROBUST,ADAPTABLE,'
                '"[{\'severity\': \'high\'}]",repo:docs/readme.md,unknown,2024-01-01',
            ]
        ),
        encoding="utf-8",
    )

    assert IssueEnricher(dataset_path=dataset_path).enrich(_issue()) is None


def test_dataset_scoring_and_case_helpers_cover_remaining_branches() -> None:
    review_case = _classification_case_type(" manual-review ")
    assert review_case is HistoricalCaseType.REVIEW_CAREFULLY
    assert _classification_case_type("mystery") is None

    score = _match_score(
        SonarIssue(
            key="issue-no-ext",
            rule="python:S1172",
            severity="LOW",
            message="Remove unused function parameter",
            location=IssueLocation(path="Makefile", line=1),
            issue_type="CODE_SMELL",
            tags=(),
            clean_code_attribute="CLEAR",
            clean_code_attribute_category="INTENTIONAL",
        ),
        {
            "rule": "python:S1172",
            "message": "Remove unused function parameter",
            "type": "CODE_SMELL",
            "severity": "LOW",
            "clean_code_attribute": "CLEAR",
            "clean_code_attribute_category": "INTENTIONAL",
            "file_extension": "no_extension",
            "tags": [],
        },
    )
    assert score == 0.95

    case = _build_case(
        _issue(),
        DatasetMatch(
            row_index=7,
            score=0.95,
            case_type=HistoricalCaseType.PREVIOUS_FIX,
            classification="fix",
            component="",
        ),
    )
    assert case.confidence == 0.82
    assert not any("matched dataset component" in item for item in case.evidence)


def test_historical_context_prefers_dataset_when_local_history_is_missing() -> None:
    summary = HistoricalEvidenceSummary(
        source_name="dataset",
        cases=(
            HistoricalIssueCase(
                issue_key="dataset:1",
                rule="python:S1172",
                message="Remove unused function parameter",
                file_path="src/app.py",
                line=12,
                disposition="fix",
                similarity_score=0.8,
                confidence=0.8,
                case_type=HistoricalCaseType.PREVIOUS_FIX,
                evidence=(),
            ),
        ),
        related_cases_count=1,
        close_cases_count=1,
        fixed_cases_count=1,
        accepted_cases_count=0,
        persistent_cases_count=0,
    )

    context = CombinedHistoricalContext(dataset=summary)

    assert context.preferred_evidence() is summary
    assert context.preferred_source_name() == "dataset"


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
