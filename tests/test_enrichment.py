from pathlib import Path

import pytest

from contextpr.enrichment import IssueEnricher, IssueHistoryRetriever
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

EVIDENCE_OPTIONS = (
    "Similar cases were usually resolved with cleanup around the flagged code.",
    "In similar cases, developers usually handled this as a cleanup task.",
    "Historically, issues like this were more often addressed by simplifying nearby code.",
    "Looking at similar cases, this was usually handled as cleanup rather than a larger change.",
)

UNUSED_VARIABLE_NEXT_STEP_OPTIONS = (
    "A good next step is to remove the variable or replace it with `_` if it is intentional.",
    "Consider deleting the variable, or rename it to `_` if it is intentionally unused.",
    (
        "A useful next step is to remove the unused variable unless it is there "
        "only as an intentional placeholder."
    ),
    (
        "Try removing the variable, or make the intent explicit with `_` if it "
        "must remain unused."
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


def test_issue_enricher_returns_quality_and_history_without_model(tmp_path: Path) -> None:
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

    assert enrichment is not None
    assert enrichment.intent_prediction is None
    assert enrichment.historical_context is not None
    assert (
        enrichment.guidance.summary
        == "Sonar flagged this because a local variable appears to be unused."
    )
    assert enrichment.guidance.next_step in UNUSED_VARIABLE_NEXT_STEP_OPTIONS


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
    assert enrichment.guidance.summary == (
        "Sonar flagged this because all branches of the condition appear to do the same thing."
    )
    assert enrichment.guidance.summary in SUMMARY_OPTIONS
    assert enrichment.guidance.explanation in EXPLANATION_OPTIONS
    assert enrichment.guidance.next_step in NEXT_STEP_OPTIONS
    assert enrichment.guidance.evidence_note in EVIDENCE_OPTIONS


def test_history_retriever_returns_none_when_dataset_is_missing(tmp_path: Path) -> None:
    retriever = IssueHistoryRetriever(tmp_path / "missing.csv")

    assert retriever.find_context(_issue()) is None


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
