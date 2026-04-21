from pathlib import Path

import pytest

from contextpr.enrichment import GuidanceLevel, IssueEnricher, IssueHistoryRetriever
from contextpr.models import IssueLocation, SonarIssue

SUMMARY_OPTIONS = (
    "Sonar flagged this because all branches of the condition appear to do the same thing.",
)

EXPLANATION_OPTIONS = (
    "This looks like a cleanup issue rather than a functional change.",
    "This seems more like code cleanup than a behavior fix.",
    "This warning points more toward simplification than a change in behavior.",
    "This looks like something to clean up rather than a functional defect.",
)

SUPPORTING_EXPLANATION_OPTIONS = (
    "This looks like a small follow-up around the flagged code rather than a large logic change.",
    "This seems more like supporting work around the flagged code than a direct behavior change.",
    "This warning usually leads to a light follow-up rather than a deeper logic rewrite.",
    "This looks like a nearby follow-up task more than a core behavior fix.",
)

NEXT_STEP_OPTIONS = (
    (
        "A good next step is to simplify the condition or remove duplicated "
        "branches if they are truly equivalent."
    ),
    "Consider collapsing the conditional if all branches are effectively doing the same work.",
    (
        "Try simplifying the control flow so each branch has a distinct outcome, "
        "or remove the condition entirely."
    ),
    (
        "A useful next step is to rewrite or remove the conditional so it no "
        "longer repeats the same behavior."
    ),
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

    retriever = IssueHistoryRetriever(dataset_path)
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
    assert context.label_distribution[0] == ("refactor", 2)
    assert context.strongest_label == "refactor"
    assert context.strongest_label_share == 0.6667
    assert context.strong_match_count == 2


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

    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )
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


def test_issue_enricher_produces_plain_language_for_duplicate_condition(tmp_path: Path) -> None:
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
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,docs,2024-01-04"
                ),
                (
                    "\"Remove this if statement or edit its code blocks so that "
                    "they're not all the same.\","
                    "python:S3923,CODE_SMELL,\"['design']\",CLEAR,INTENTIONAL,"
                    "\"[{'severity': 'HIGH'}]\",repo:src/app.py,docs,2024-01-05"
                ),
            ]
        ),
        encoding="utf-8",
    )

    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )
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

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.summary == (
        "Sonar flagged this because all branches of the condition appear to do the same thing."
    )
    assert enrichment.guidance.summary in SUMMARY_OPTIONS
    assert enrichment.guidance.explanation in SUPPORTING_EXPLANATION_OPTIONS
    assert enrichment.guidance.next_step in NEXT_STEP_OPTIONS
    assert enrichment.guidance.evidence_note == (
        "Historical note: in a small set of similar cases, developers leaned toward "
        "supporting updates."
    )


def test_history_retriever_returns_none_when_dataset_is_missing(tmp_path: Path) -> None:
    retriever = IssueHistoryRetriever(tmp_path / "missing.csv")

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
    retriever = IssueHistoryRetriever(dataset_path)

    context = retriever.find_context(_issue())

    assert context is not None
    assert context.label_distribution == (("refactor", 1),)


def test_history_retriever_rejects_unsupported_dataset_format(tmp_path: Path) -> None:
    dataset_path = tmp_path / "issues.json"
    dataset_path.write_text("[]", encoding="utf-8")
    retriever = IssueHistoryRetriever(dataset_path)

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
    retriever = IssueHistoryRetriever(dataset_path)

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
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )

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
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )

    enrichment = enricher.enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
    assert enrichment.guidance.summary is None
    assert enrichment.guidance.explanation is None
    assert enrichment.guidance.next_step is None
    assert enrichment.guidance.evidence_note == (
        "Historical note: in a small set of similar cases, developers leaned toward "
        "routine cleanup."
    )


def test_issue_enricher_uses_rule_id_before_message_text(tmp_path: Path) -> None:
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=tmp_path / "missing.csv",
    )

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

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.summary == (
        "Sonar flagged this because all branches of the condition appear to do the same thing."
    )


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
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )

    enrichment = enricher.enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
        "Historical note: similar cases were usually handled as routine cleanup."
    )


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
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )

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
    assert enrichment.guidance.evidence_note == (
        "Historical note: similar cases were split between behavior-oriented fixes "
        "and routine cleanup."
    )


def test_issue_enricher_does_not_load_optional_intent_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.joblib"
    model_path.write_text("placeholder", encoding="utf-8")

    def fail_if_loaded(_path: Path) -> object:
        raise AssertionError("Intent model should not be loaded by IssueEnricher")

    monkeypatch.setattr(
        "contextpr.enrichment.intent.joblib.load",
        fail_if_loaded,
    )
    enricher = IssueEnricher(
        model_path=model_path,
        dataset_path=tmp_path / "missing.csv",
    )

    enrichment = enricher.enrich(
        SonarIssue(
            key="issue-generic",
            rule="python:S100",
            severity="MINOR",
            message="Possible null pointer dereference",
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="BUG",
        )
    )

    assert enrichment is not None
    assert enrichment.intent_prediction is None
    assert enrichment.guidance.level is GuidanceLevel.DETAILED
    assert enrichment.guidance.explanation not in EXPLANATION_OPTIONS


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
