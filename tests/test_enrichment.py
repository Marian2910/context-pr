from pathlib import Path

import pytest

from contextpr.enrichment import (
    CombinedHistoricalContext,
    DeveloperGuidance,
    DeterministicGuidanceMessageService,
    GlobalDatasetHistoryRetriever,
    GuidanceLevel,
    HistoricalContext,
    IssueEnricher,
    IssueContextEvidence,
    LocalPullRequestHistoryRetriever,
    LocalSonarHistoryRetriever,
)
from contextpr.models import IssueLocation, SonarIssue
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    PullRequestReviewCommentRecord,
    SonarIssueRecord,
)


def test_history_retriever_summarizes_similar_issues(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Remove the unused function parameter kwargs\","
                    "python:S1172,CODE_SMELL,\"['unused']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'LOW'}]\",repo:src/app.py,refactor,2024-01-01"
                ),
                (
                    "\"Remove the unused function parameter args\","
                    "python:S1172,CODE_SMELL,\"['unused']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'LOW'}]\",repo:src/app.py,refactor,2024-01-02"
                ),
                (
                    "\"Fix a broken condition\",python:S2259,BUG,\"['bug']\","
                    "COMPLETE,INTENTIONAL,\"[{'severity': 'HIGH'}]\","
                    "repo:src/app.py,fix,2024-01-03"
                ),
            ]
        ),
        encoding="utf-8",
    )

    retriever = GlobalDatasetHistoryRetriever(dataset_path)
    context = retriever.find_context(
        SonarIssue(
            key="issue-1",
            rule="python:S1172",
            severity="LOW",
            message="Remove the unused function parameter kwargs",
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="CODE_SMELL",
            tags=("unused",),
            clean_code_attribute="CLEAR",
            clean_code_attribute_category="INTENTIONAL",
        )
    )

    assert context is not None
    assert context.sample_size == 3
    assert context.same_rule_matches == 2
    assert context.same_scope_matches == 3
    assert context.same_path_family_matches == 3
    assert context.same_exact_path_matches == 3
    assert context.same_path_family_share == 1.0
    assert context.maintenance_distribution[0] == ("cleanup", 2)
    assert context.dominant_maintenance == "cleanup"
    assert context.dominant_maintenance_share == 0.6667
    assert context.strong_match_count == 3


def test_issue_enricher_skips_trivial_issue_without_grounded_history(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Replace unused local variable protocol with _\","
                    "python:S1481,CODE_SMELL,\"['unused']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'LOW'}]\",repo:src/views.py,style,2024-02-01"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enricher = IssueEnricher(dataset_path=dataset_path)
    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-2",
            rule="python:S1481",
            severity="LOW",
            message="Replace unused local variable protocol with _",
            location=IssueLocation(path="src/views.py", line=4),
            issue_type="CODE_SMELL",
            tags=("unused",),
            clean_code_attribute="CLEAR",
            clean_code_attribute_category="INTENTIONAL",
        )
    )

    assert enrichment is None


def test_issue_enricher_skips_duplicate_condition_when_sonar_is_self_explanatory(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,docs,2024-01-01"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,test,2024-01-02"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-03"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-04"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enricher = IssueEnricher(dataset_path=dataset_path)
    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-3",
            rule="python:S3923",
            severity="MAJOR",
            message=(
                "Remove this if statement or edit its code blocks so that they're "
                "not all the same."
            ),
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
            clean_code_attribute="CLEAR",
            clean_code_attribute_category="INTENTIONAL",
        )
    )

    assert enrichment is None


def test_issue_enricher_adds_duplicate_condition_context_for_behavioral_history(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,fix,2024-01-01"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,fix,2024-01-02"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,fix,2024-01-03"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-04"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enricher = IssueEnricher(dataset_path=dataset_path)
    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-3b",
            rule="python:S3923",
            severity="MAJOR",
            message=(
                "Remove this if statement or edit its code blocks so that they're "
                "not all the same."
            ),
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
            clean_code_attribute="CLEAR",
            clean_code_attribute_category="INTENTIONAL",
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.explanation is not None


def test_history_retriever_returns_none_when_dataset_is_missing(tmp_path: Path) -> None:
    retriever = GlobalDatasetHistoryRetriever(tmp_path / "missing.csv")

    assert retriever.find_context(_issue()) is None


def test_history_retriever_handles_dataset_without_creation_date(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification"
                ),
                (
                    "\"Remove unused parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor"
                ),
            ]
        ),
        encoding="utf-8",
    )
    retriever = GlobalDatasetHistoryRetriever(dataset_path)

    context = retriever.find_context(_issue())

    assert context is not None
    assert context.maintenance_distribution == (("cleanup", 1),)


def test_history_retriever_rejects_unsupported_dataset_format(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.json"
    dataset_path.write_text("[]", encoding="utf-8")
    retriever = GlobalDatasetHistoryRetriever(dataset_path)

    with pytest.raises(ValueError, match="Unsupported dataset format"):
        retriever.find_context(_issue())


def test_history_retriever_returns_none_when_no_rows_match(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Totally unrelated\",python:S1,BUG,\"[]\",COMPLETE,"
                    "CONVENTIONAL,\"[{'severity': 'HIGH'}]\",repo:README,fix,"
                    "2024-01-01"
                ),
            ]
        ),
        encoding="utf-8",
    )
    retriever = GlobalDatasetHistoryRetriever(dataset_path)

    assert retriever.find_context(_issue()) is None


def test_issue_enricher_omits_history_note_for_weak_historical_context(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    rows = [
        (
            "message,rule,type,tags,clean_code_attribute,"
            "clean_code_attribute_category,impacts,component,"
            "ccs_classification,creation_date"
        )
    ]
    rows.extend(
        (
            "\"Clean up nearby code\",python:S9999,CODE_SMELL,\"['unused']\","
            "CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\",repo:src/app.py,"
            f"refactor,2024-01-0{index}"
        )
        for index in range(1, 6)
    )
    dataset_path.write_text("\n".join(rows), encoding="utf-8")
    enricher = IssueEnricher(dataset_path=dataset_path)

    enrichment = enricher.enrich(_issue())

    assert enrichment is None


def test_issue_enricher_uses_minimal_history_note_for_trivial_issue(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    rows = [
        (
            "message,rule,type,tags,clean_code_attribute,"
            "clean_code_attribute_category,impacts,component,"
            "ccs_classification,creation_date"
        )
    ]
    rows.extend(
        (
            "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
            "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
            f"repo:src/app.py,refactor,2024-01-0{index}"
        )
        for index in range(1, 6)
    )
    dataset_path.write_text("\n".join(rows), encoding="utf-8")
    enricher = IssueEnricher(dataset_path=dataset_path)

    enrichment = enricher.enrich(_issue())

    assert enrichment is None


def test_combined_historical_context_prefers_local_sources_before_global() -> None:
    local_history = IssueContextEvidence(
        sample_size=2,
        same_rule_matches=2,
        same_scope_matches=2,
        same_path_family_matches=2,
        strong_match_count=2,
        dominant_maintenance="behavior",
        dominant_maintenance_share=1.0,
        maintenance_distribution=(("behavior", 2),),
    )
    global_history = IssueContextEvidence(
        sample_size=5,
        same_rule_matches=4,
        same_scope_matches=5,
        same_path_family_matches=5,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.8,
        maintenance_distribution=(("cleanup", 4), ("behavior", 1)),
    )

    combined = CombinedHistoricalContext(
        local_sonar=local_history,
        global_dataset=global_history,
    )

    assert combined.preferred_evidence() is local_history
    assert combined.preferred_source_name() == "local_sonar"


def test_issue_enricher_wraps_dataset_history_as_global_context(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-01"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-02"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-03"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-04"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(_issue())

    assert enrichment is None


def test_issue_enricher_requires_store_when_local_history_is_enabled(tmp_path: Path) -> None:
    enricher = IssueEnricher(dataset_path=tmp_path / "missing.csv", enable_local_history=True)

    with pytest.raises(NotImplementedError, match="configured repository store"):
        enricher.enrich(_issue())


def test_issue_enricher_uses_local_sonar_history_when_available(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 6):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"issue-{index}",
                rule="python:S1172",
                issue_type="CODE_SMELL",
                severity="LOW",
                component="src/app.py",
                message="Remove unused function parameter",
                status="CLOSED",
                resolution="FIXED",
                updated_at=f"2026-05-1{index}T10:00:00+00:00",
            ),
        )

    enrichment = IssueEnricher(
        dataset_path=tmp_path / "missing.csv",
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    assert enrichment.historical_context is not None
    assert enrichment.historical_context.local_sonar is not None
    assert enrichment.historical_context.global_dataset is None
    assert enrichment.historical_context.preferred_source_name() == "local_sonar"
    assert enrichment.guidance.evidence_note is not None
    assert "similar cases of this rule were usually fixed" in enrichment.guidance.evidence_note
    assert "reasonable fix to keep in this pr" in enrichment.guidance.evidence_note.lower()


def test_issue_enricher_prefers_local_sonar_over_global_dataset_when_both_exist(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,2024-02-01"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,2024-02-02"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,2024-02-03"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,2024-02-04"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,2024-02-05"
                ),
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 6):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"local-{index}",
                rule="python:S3923",
                issue_type="CODE_SMELL",
                severity="MAJOR",
                component="src/app.py",
                message="Remove this if statement or edit its code blocks so that they're not all the same.",
                status="OPEN",
                updated_at=f"2026-05-1{index}T10:00:00+00:00",
            ),
        )

    enrichment = IssueEnricher(
        dataset_path=dataset_path,
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(
        SonarIssue(
            key="issue-local-preferred",
            rule="python:S3923",
            severity="MAJOR",
            message="Remove this if statement or edit its code blocks so that they're not all the same.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.historical_context is not None
    assert enrichment.historical_context.local_sonar is not None
    assert enrichment.historical_context.global_dataset is None
    assert enrichment.historical_context.preferred_source_name() == "local_sonar"
    assert enrichment.guidance.level is GuidanceLevel.CONTEXTUAL
    assert enrichment.guidance.evidence_note is not None
    assert "similar cases of this rule often remained open once introduced" in (
        enrichment.guidance.evidence_note
    )
    assert "follow-up decision" in enrichment.guidance.evidence_note


def test_issue_enricher_uses_local_git_history_when_local_sonar_is_too_weak(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="same-rule-history",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            status="OPEN",
            updated_at="2026-05-10T10:00:00+00:00",
        ),
    )
    for index in range(1, 6):
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
        dataset_path=tmp_path / "missing.csv",
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is None


def test_issue_enricher_uses_global_dataset_only_as_fallback_when_local_history_is_weak(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,creation_date"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-01"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-02"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-03"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-04"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="weak-local-history",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            status="OPEN",
            updated_at="2026-05-10T10:00:00+00:00",
        ),
    )

    enrichment = IssueEnricher(
        dataset_path=dataset_path,
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is None


def test_issue_enricher_can_disable_local_git_history_even_when_git_data_exists(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 6):
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
        dataset_path=tmp_path / "missing.csv",
        enable_local_history=True,
        enable_local_git_history=False,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is None


def test_issue_enricher_can_fall_back_to_review_comment_history(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=5,
            title="Review semantics",
            updated_at="2026-05-16T10:00:00Z",
        ),
        review_comments=(
            PullRequestReviewCommentRecord(
                comment_id=11,
                pr_number=5,
                body="Please verify that this is behavior-sensitive before collapsing these branches.",
                file_path="src/app.py",
                line=12,
                author_role="reviewer",
            ),
            PullRequestReviewCommentRecord(
                comment_id=12,
                pr_number=5,
                body="This looks behavior-sensitive, so confirm the current semantics first.",
                file_path="src/app.py",
                line=14,
                author_role="reviewer",
            ),
            PullRequestReviewCommentRecord(
                comment_id=13,
                pr_number=5,
                body="Before refactoring this, treat the duplicated branches as behavior-sensitive and preserve semantics.",
                file_path="src/app.py",
                line=16,
                author_role="reviewer",
            ),
            PullRequestReviewCommentRecord(
                comment_id=14,
                pr_number=5,
                body="This should be treated as behavior-sensitive until the current outcome is verified.",
                file_path="src/app.py",
                line=18,
                author_role="reviewer",
            ),
            PullRequestReviewCommentRecord(
                comment_id=15,
                pr_number=5,
                body="Please confirm the existing behavior-sensitive path before simplifying the condition.",
                file_path="src/app.py",
                line=20,
                author_role="reviewer",
            ),
        ),
    )

    enrichment = IssueEnricher(
        dataset_path=tmp_path / "missing.csv",
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(
        SonarIssue(
            key="review-fallback",
            rule="python:S3923",
            severity="MAJOR",
            message="Remove this if statement or edit its code blocks so that they're not all the same.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.historical_context is not None
    assert enrichment.historical_context.local_review_comments is not None
    assert enrichment.historical_context.preferred_source_name() == "local_review_comments"
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.explanation is not None
    assert "check" in enrichment.guidance.explanation.lower() or "verify" in enrichment.guidance.explanation.lower()


def test_local_pull_request_history_retriever_finds_strong_same_file_signal(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for pr_number in range(1, 4):
        store.upsert_pull_request(
            "octo/example",
            PullRequestRecord(
                pr_number=pr_number,
                title=f"Refactor handler {pr_number}",
                body="cleanup pass",
                updated_at=f"2026-05-1{pr_number}T10:00:00Z",
            ),
            files=(
                PullRequestFileRecord(pr_number=pr_number, file_path="src/app.py"),
            ),
        )
    for index in range(1, 4):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"issue-{index}",
                rule="python:S3923",
                issue_type="CODE_SMELL",
                severity="MAJOR",
                component="src/app.py",
                message="Remove this if statement or edit its code blocks so that they're not all the same.",
                status="OPEN",
                updated_at=f"2026-05-1{index}T12:00:00+00:00",
            ),
        )

    context = LocalPullRequestHistoryRetriever(store, "octo/example").find_context(
        SonarIssue(
            key="pr-history",
            rule="python:S3923",
            severity="MAJOR",
            message="Remove this if statement or edit its code blocks so that they're not all the same.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert context is not None
    assert context.same_exact_path_matches == 3
    assert context.dominant_maintenance == "cleanup"


def test_issue_enricher_surfaces_local_sonar_history_for_recurrent_trivial_smell(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    for index in range(1, 6):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"recurrent-{index}",
                rule="python:S1172",
                issue_type="CODE_SMELL",
                severity="LOW",
                component="src/app.py",
                message="Remove unused function parameter",
                status="CLOSED",
                resolution="FIXED",
                updated_at=f"2026-05-1{index}T10:00:00+00:00",
            ),
        )

    enrichment = IssueEnricher(
        dataset_path=tmp_path / "missing.csv",
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
    assert enrichment.guidance.evidence_note is not None
    assert "reasonable fix to keep in this pr" in enrichment.guidance.evidence_note.lower()


def test_local_sonar_history_links_fixed_issue_to_recent_file_touching_pr(
    tmp_path: Path,
) -> None:
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
    for index in range(1, 3):
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
                end_line=20 + index,
            ),
        )

    context = LocalSonarHistoryRetriever(store, "octo/example").find_context(_issue())

    assert context is not None
    assert len(context.fix_references) == 1
    reference = context.fix_references[0]
    assert reference.pr_number == 42
    assert reference.pr_url == "https://github.com/octo/example/pull/42"
    assert reference.file_url == "https://github.com/octo/example/pull/42/files"
    assert reference.confidence >= 0.9
    assert "same Sonar rule `python:S1172`" in reference.evidence


def test_local_sonar_score_prefers_same_rule_and_code_context() -> None:
    issue = _issue()
    same_rule_score = LocalSonarHistoryRetriever._score_record(
        issue,
        SonarIssueRecord(
            issue_key="same-rule",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            tags_json='["unused"]',
            updated_at="2026-05-19T10:00:00+00:00",
        ),
    )
    related_rule_score = LocalSonarHistoryRetriever._score_record(
        issue,
        SonarIssueRecord(
            issue_key="related-rule",
            rule="python:S1481",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused local variable",
            tags_json='["unused"]',
            updated_at="2026-05-19T10:00:00+00:00",
        ),
    )
    unrelated_score = LocalSonarHistoryRetriever._score_record(
        issue,
        SonarIssueRecord(
            issue_key="unrelated",
            rule="python:S9999",
            issue_type="BUG",
            severity="HIGH",
            component="docs/readme.md",
            message="Validate this security-sensitive configuration",
            updated_at="2026-05-19T10:00:00+00:00",
        ),
    )

    assert same_rule_score > related_rule_score > unrelated_score


def test_local_sonar_score_applies_recency_decay() -> None:
    issue = _issue()
    recent_score = LocalSonarHistoryRetriever._score_record(
        issue,
        SonarIssueRecord(
            issue_key="recent",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            updated_at="2026-05-19T10:00:00+00:00",
        ),
    )
    old_score = LocalSonarHistoryRetriever._score_record(
        issue,
        SonarIssueRecord(
            issue_key="old",
            rule="python:S1172",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/app.py",
            message="Remove unused function parameter",
            updated_at="2024-05-19T10:00:00+00:00",
        ),
    )

    assert recent_score > old_score
    assert old_score >= 4.0


def test_local_sonar_history_falls_back_to_last_prs_when_time_window_is_sparse(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=41,
            title="Recent unrelated cleanup",
            state="closed",
            merged_at="2026-05-14T10:00:00+00:00",
            updated_at="2026-05-14T10:30:00+00:00",
        ),
        files=(PullRequestFileRecord(pr_number=41, file_path="src/other.py"),),
    )
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=12,
            title="Remove unused parameters",
            state="closed",
            merged_at="2024-05-14T10:00:00+00:00",
            updated_at="2024-05-14T10:30:00+00:00",
        ),
        files=(PullRequestFileRecord(pr_number=12, file_path="src/app.py"),),
    )
    for index in range(1, 3):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"old-fixed-{index}",
                rule="python:S1172",
                issue_type="CODE_SMELL",
                severity="LOW",
                component="src/app.py",
                message="Remove unused function parameter",
                status="CLOSED",
                resolution="FIXED",
                updated_at=f"2024-05-15T1{index}:00:00+00:00",
                line=20 + index,
            ),
        )

    context = LocalSonarHistoryRetriever(store, "octo/example").find_context(_issue())

    assert context is not None
    assert context.fix_references
    assert context.fix_references[0].pr_number == 12


def test_local_sonar_history_caps_dense_window_to_recent_prs(tmp_path: Path) -> None:
    pull_requests = [
        PullRequestRecord(
            pr_number=index,
            title=f"PR {index}",
            state="closed",
            merged_at="2026-05-14T10:00:00+00:00",
            updated_at="2026-05-14T10:30:00+00:00",
        )
        for index in range(1, 503)
    ]

    bounded = LocalSonarHistoryRetriever._bounded_fix_reference_pull_requests(
        pull_requests,
    )

    assert len(bounded) == 500
    assert 1 not in {pull_request.pr_number for pull_request in bounded}


def test_local_sonar_fix_references_use_dedicated_candidates_beyond_similarity_shortlist(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.db")
    store.upsert_pull_request(
        "octo/example",
        PullRequestRecord(
            pr_number=99,
            title="Fix duplicated literal in sonar history example",
            state="closed",
            merged_at="2026-05-14T10:00:00+00:00",
            updated_at="2026-05-14T10:30:00+00:00",
        ),
        files=(PullRequestFileRecord(pr_number=99, file_path="src/history_example.py"),),
    )
    store.upsert_sonar_issue(
        "octo/example",
        SonarIssueRecord(
            issue_key="fixed-same-file",
            rule="python:S1192",
            issue_type="CODE_SMELL",
            severity="LOW",
            component="src/history_example.py",
            message=(
                "Define a constant instead of duplicating this literal "
                "'Request completed with warnings' 5 times."
            ),
            status="CLOSED",
            resolution="FIXED",
            updated_at="2026-05-15T10:00:00+00:00",
            line=12,
            end_line=12,
        ),
    )

    for index in range(30):
        store.upsert_sonar_issue(
            "octo/example",
            SonarIssueRecord(
                issue_key=f"open-message-match-{index}",
                rule="python:S1192",
                issue_type="CODE_SMELL",
                severity="LOW",
                component=f"src/nearby_{index}.py",
                message=(
                    "Define a constant instead of duplicating this literal "
                    "'ContextPR similarity baseline for historical sonar issues' 3 times."
                ),
                status="OPEN",
                resolution=None,
                updated_at=f"2026-05-{(index % 9) + 10:02d}T10:00:00+00:00",
            ),
        )

    issue = SonarIssue(
        key="issue-s1192",
        rule="python:S1192",
        severity="LOW",
        message=(
            "Define a constant instead of duplicating this literal "
            "'ContextPR similarity baseline for historical sonar issues' 3 times."
        ),
        location=IssueLocation(path="src/history_example.py", line=15),
        issue_type="CODE_SMELL",
        tags=("design",),
        clean_code_attribute="CLEAR",
        clean_code_attribute_category="INTENTIONAL",
    )

    context = LocalSonarHistoryRetriever(store, "octo/example").find_context(issue)

    assert context is not None
    assert context.fix_references
    assert context.fix_references[0].pr_number == 99


def test_issue_enricher_uses_global_dataset_for_persistent_duplicate_branches(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,status,creation_date"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,open,2024-02-01"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,open,2024-02-02"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,open,2024-02-03"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,open,2024-02-04"
                ),
                (
                    "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
                    "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
                    "refactor,open,2024-02-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(
        SonarIssue(
            key="issue-persistent-global",
            rule="python:S3923",
            severity="MAJOR",
            message="Remove this if statement or edit its code blocks so that they're not all the same.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.CONTEXTUAL
    assert enrichment.guidance.evidence_note is not None
    assert "follow-up decision" in enrichment.guidance.evidence_note


def test_issue_enricher_uses_rule_id_before_message_text(tmp_path: Path) -> None:
    enricher = IssueEnricher(dataset_path=tmp_path / "missing.csv")

    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-rule",
            rule="python:S3923",
            severity="MAJOR",
            message="Sonar wording changed for this rule.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is None


def test_issue_enricher_uses_confidence_aware_history_wording(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    rows = [
        (
            "message,rule,type,tags,clean_code_attribute,"
            "clean_code_attribute_category,impacts,component,"
            "ccs_classification,creation_date"
        )
    ]
    rows.extend(
        (
            "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
            "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
            f"repo:src/app.py,refactor,2024-01-{index:02d}"
        )
        for index in range(1, 16)
    )
    dataset_path.write_text("\n".join(rows), encoding="utf-8")
    enricher = IssueEnricher(dataset_path=dataset_path)

    enrichment = enricher.enrich(_issue())

    assert enrichment is None


def test_issue_enricher_reports_mixed_history_when_buckets_are_close(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "issues.csv"
    rows = [
        (
            "message,rule,type,tags,clean_code_attribute,"
            "clean_code_attribute_category,impacts,component,"
            "ccs_classification,creation_date"
        )
    ]
    rows.extend(
        (
            "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
            "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
            f"fix,2024-02-{index:02d}"
        )
        for index in range(1, 4)
    )
    rows.extend(
        (
            "\"Review branch behavior\",python:S3923,CODE_SMELL,\"['design']\","
            "CLEAR,INTENTIONAL,\"[{'severity': 'HIGH'}]\",repo:src/app.py,"
            f"refactor,2024-02-{index:02d}"
        )
        for index in range(4, 6)
    )
    dataset_path.write_text("\n".join(rows), encoding="utf-8")
    enricher = IssueEnricher(dataset_path=dataset_path)

    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-mixed",
            rule="python:S3923",
            severity="MAJOR",
            message="Changed wording",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.explanation is not None
    assert "check" in enrichment.guidance.explanation.lower() or "verify" in enrichment.guidance.explanation.lower()


def test_issue_enricher_prefers_disposition_history_when_available(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.csv"
    dataset_path.write_text(
        "\n".join(
            [
                (
                    "message,rule,type,tags,clean_code_attribute,"
                    "clean_code_attribute_category,impacts,component,"
                    "ccs_classification,status,creation_date"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,resolved,2024-01-01"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,resolved,2024-01-02"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,resolved,2024-01-03"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,open,2024-01-04"
                ),
                (
                    "\"Remove unused function parameter\",python:S1172,CODE_SMELL,"
                    "\"['unused']\",CLEAR,INTENTIONAL,\"[{'severity': 'LOW'}]\","
                    "repo:src/app.py,refactor,resolved,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )
    enricher = IssueEnricher(dataset_path=dataset_path)

    enrichment = enricher.enrich(_issue())

    assert enrichment is None


def test_issue_enricher_helper_branches(tmp_path: Path) -> None:
    enricher = IssueEnricher(dataset_path=tmp_path / "missing.csv")
    message_service = DeterministicGuidanceMessageService()

    assert enricher._issue_pattern(
        SonarIssue(
            key="dup-literal",
            rule="python:S1",
            severity="MINOR",
            message='Define a constant instead of duplicating this literal "x".',
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="CODE_SMELL",
        )
    ) == "self_explanatory_cleanup"
    assert enricher._maintainability_focus(
        HistoricalContext(
            sample_size=6,
            same_rule_matches=3,
            same_scope_matches=6,
            same_path_family_matches=6,
            strong_match_count=4,
            dominant_maintenance="behavior",
            dominant_maintenance_share=0.6667,
            maintenance_distribution=(("behavior", 4), ("cleanup", 2)),
        )
    ) == "behavior_sensitive"
    assert enricher._has_actionable_history(
        HistoricalContext(
            sample_size=6,
            same_rule_matches=3,
            same_scope_matches=6,
            same_path_family_matches=6,
            strong_match_count=4,
            dominant_maintenance="cleanup",
            dominant_maintenance_share=0.6667,
            maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
            same_exact_path_matches=2,
            same_path_family_share=1.0,
        )
    ) is True
    assert enricher._maintainability_focus(
        HistoricalContext(
            sample_size=6,
            same_rule_matches=3,
            same_scope_matches=6,
            same_path_family_matches=6,
            strong_match_count=4,
            dominant_maintenance="supporting",
            dominant_maintenance_share=0.6667,
            maintenance_distribution=(("supporting", 4), ("cleanup", 2)),
            same_path_family_share=1.0,
        )
    ) == "accumulating_hotspot"
    assert enricher._build_maintainability_evidence_note(
        HistoricalContext(
            sample_size=6,
            same_rule_matches=3,
            same_scope_matches=6,
            same_path_family_matches=6,
            strong_match_count=4,
            dominant_maintenance="supporting",
            dominant_maintenance_share=0.6667,
            maintenance_distribution=(("supporting", 4), ("cleanup", 2)),
        )
    ) is not None
    assert IssueEnricher._is_split_distribution(
        (("cleanup", 1), ("behavior", 1)),
        sample_size=0,
    ) is False
    assert message_service.is_local_history_source("local_prs") is True
    assert message_service.is_local_history_source("global_dataset") is False


def test_issue_enricher_adds_generic_guidance_for_behavior_sensitive_cleanup(
    tmp_path: Path,
) -> None:
    enricher = IssueEnricher(dataset_path=tmp_path / "missing.csv")

    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-s1515",
            rule="python:S1515",
            severity="MAJOR",
            message=(
                'Add a parameter to the parent lambda function and use variable "prefix" '
                'as its default value; The value of "prefix" might change at the next loop iteration.'
            ),
            location=IssueLocation(path="src/app.py", line=21),
            issue_type="CODE_SMELL",
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.explanation is not None
    assert "prefix" not in enrichment.guidance.explanation
    assert "check" in enrichment.guidance.explanation.lower() or "verify" in enrichment.guidance.explanation.lower()
    assert enrichment.guidance.next_step is not None
    assert "prefix" not in enrichment.guidance.next_step
    assert "path" in enrichment.guidance.next_step.lower() or "surrounding code" in enrichment.guidance.next_step.lower()


def _issue() -> SonarIssue:
    return SonarIssue(
        key="issue-x",
        rule="python:S1172",
        severity="LOW",
        message="Remove the unused function parameter kwargs",
        location=IssueLocation(path="src/app.py", line=10),
        issue_type="CODE_SMELL",
        tags=("unused",),
        clean_code_attribute="CLEAR",
        clean_code_attribute_category="INTENTIONAL",
    )
