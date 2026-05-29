from pathlib import Path

import pytest

from contextpr.enrichment import (
    CombinedHistoricalContext,
    DeveloperGuidance,
    DeterministicGuidanceMessageService,
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


def test_combined_historical_context_prefers_local_sources() -> None:
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

    combined = CombinedHistoricalContext(
        local_sonar=local_history,
    )

    assert combined.preferred_evidence() is local_history
    assert combined.preferred_source_name() == "local_sonar"


def test_issue_enricher_requires_store_when_local_history_is_enabled(tmp_path: Path) -> None:
    enricher = IssueEnricher(enable_local_history=True)

    with pytest.raises(NotImplementedError, match="configured repository store"):
        enricher.enrich(_issue())


def test_issue_enricher_uses_dataset_history_as_fallback_for_fresh_repository(
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
                    "\"Remove this if statement or edit its code blocks so that they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-01"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-02"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-03"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-04"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,refactor,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enrichment = IssueEnricher(dataset_path=dataset_path).enrich(
        SonarIssue(
            key="fresh-repo-issue",
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
    assert enrichment.historical_context.global_dataset is not None
    assert enrichment.historical_context.preferred_source_name() == "global_dataset"
    assert enrichment.guidance.evidence_note is not None
    assert "In similar issues from other repositories" in enrichment.guidance.evidence_note
    assert "In this repository" not in enrichment.guidance.evidence_note


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
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    assert enrichment.historical_context is not None
    assert enrichment.historical_context.local_sonar is not None
    assert enrichment.historical_context.preferred_source_name() == "local_sonar"
    assert enrichment.guidance.evidence_note is not None
    assert "was usually addressed" in enrichment.guidance.evidence_note
    assert "appeared multiple times in this file" in enrichment.guidance.evidence_note.lower()


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
    assert enrichment.guidance.level is GuidanceLevel.CONTEXTUAL
    assert enrichment.guidance.evidence_note is not None
    assert "review comments for this file" in enrichment.guidance.evidence_note.lower()
    assert "keeps coming up in review" in enrichment.guidance.evidence_note.lower()


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
        enable_local_history=True,
        history_store=store,
        repository_key="octo/example",
    ).enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
    assert enrichment.guidance.evidence_note is not None
    assert "appeared multiple times in this file and was usually addressed" in enrichment.guidance.evidence_note.lower()


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


def test_local_sonar_fix_reference_confidence_supports_nearby_matches() -> None:
    issue = _issue()
    same_file_record = SonarIssueRecord(
        issue_key="same-file",
        rule="python:S1172",
        issue_type="CODE_SMELL",
        severity="LOW",
        component="src/app.py",
        message="Remove the unused function parameter kwargs",
        status="CLOSED",
        resolution="FIXED",
        updated_at="2026-05-15T10:00:00+00:00",
        line=12,
    )
    same_folder_record = SonarIssueRecord(
        issue_key="same-folder",
        rule="python:S1172",
        issue_type="CODE_SMELL",
        severity="LOW",
        component="src/helpers.py",
        message="Remove the unused function parameter kwargs",
        status="CLOSED",
        resolution="FIXED",
        updated_at="2026-05-15T10:00:00+00:00",
        line=18,
    )
    different_folder_record = SonarIssueRecord(
        issue_key="different-folder",
        rule="python:S1172",
        issue_type="CODE_SMELL",
        severity="LOW",
        component="docs/readme.py",
        message="Remove the unused function parameter kwargs",
        status="CLOSED",
        resolution="FIXED",
        updated_at="2026-05-15T10:00:00+00:00",
        line=22,
    )

    exact_files = [PullRequestFileRecord(pr_number=42, file_path="src/app.py")]
    same_folder_files = [PullRequestFileRecord(pr_number=42, file_path="src/helpers.py")]
    different_folder_files = [PullRequestFileRecord(pr_number=42, file_path="docs/readme.py")]

    same_file_confidence = LocalSonarHistoryRetriever._fix_reference_confidence(
        issue,
        same_file_record,
        exact_files,
    )
    same_folder_confidence = LocalSonarHistoryRetriever._fix_reference_confidence(
        issue,
        same_folder_record,
        same_folder_files,
    )
    different_folder_confidence = LocalSonarHistoryRetriever._fix_reference_confidence(
        issue,
        different_folder_record,
        different_folder_files,
    )

    assert same_file_confidence > same_folder_confidence > different_folder_confidence
    assert same_file_confidence >= 0.95
    assert same_folder_confidence >= 0.7
    assert different_folder_confidence >= 0.7


def test_local_sonar_fix_reference_evidence_mentions_nearby_match_reasons() -> None:
    issue = _issue()
    same_folder_record = SonarIssueRecord(
        issue_key="same-folder",
        rule="python:S1172",
        issue_type="CODE_SMELL",
        severity="LOW",
        component="src/helpers.py",
        message="Remove the unused function parameter kwargs",
        status="CLOSED",
        resolution="FIXED",
        updated_at="2026-05-15T10:00:00+00:00",
        line=18,
    )

    evidence = LocalSonarHistoryRetriever._fix_reference_evidence(
        issue,
        same_folder_record,
        [PullRequestFileRecord(pr_number=42, file_path="src/helpers.py")],
    )

    assert "same path family `src/helpers.py`" not in evidence
    assert "same path family `src`" in evidence
    assert "similar issue text and code context" in evidence


def test_issue_enricher_uses_rule_id_before_message_text(tmp_path: Path) -> None:
    enricher = IssueEnricher()

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


def test_issue_enricher_helper_branches(tmp_path: Path) -> None:
    enricher = IssueEnricher()
    message_service = DeterministicGuidanceMessageService()
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
    assert message_service.is_local_history_source("local_prs") is True


def test_issue_enricher_adds_generic_guidance_for_behavior_sensitive_cleanup(
    tmp_path: Path,
) -> None:
    enricher = IssueEnricher()

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
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.explanation is None
    assert enrichment.guidance.next_step == "Review the surrounding code before changing it."
    assert enrichment.guidance.evidence_note is None


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
