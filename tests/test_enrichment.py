import json
from pathlib import Path
from urllib import error

import pytest

from contextpr.enrichment import (
    DeveloperGuidance,
    GuidanceLevel,
    HistoricalContext,
    IssueEnricher,
    IssueHistoryRetriever,
    LLMVerbalizerSettings,
    LightweightLLMGuidanceVerbalizer,
)
from contextpr.models import IssueLocation, SonarIssue

<<<<<<< HEAD
=======
EXPLANATION_OPTIONS = (
    "This is probably safe to simplify if the current structure is not intentional.",
    "This looks like code that can be simplified without changing the intended behavior.",
    "The main value here is to make the code easier to read and maintain.",
    "This is a good candidate for a small refactor if there is no hidden intent in the current structure.",
)

NEXT_STEP_OPTIONS = (
    (
        "Before simplifying the conditional, verify that the repeated branches "
        "are not intentionally preserving behavior or readability."
    ),
    "Check whether the duplicated branches are intentional before collapsing the conditional.",
    (
        "Verify that the identical branches are not documenting an intentional "
        "distinction before removing the duplication."
    ),
    (
        "Review whether the repeated branches are deliberately kept separate "
        "before simplifying the control flow."
    ),
)
>>>>>>> origin/main

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
    assert context.same_scope_matches == 3
    assert context.same_path_family_matches == 3
<<<<<<< HEAD
    assert context.same_exact_path_matches == 3
    assert context.same_path_family_share == 1.0
=======
>>>>>>> origin/main
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

<<<<<<< HEAD
    enricher = IssueEnricher(dataset_path=dataset_path)
=======
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )
>>>>>>> origin/main
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
<<<<<<< HEAD
    assert "preserving behavior" in (enrichment.guidance.next_step or "")
    assert enrichment.guidance.evidence_note == (
        "Retrieved historical matches clustered around the same file path and were split between "
        "behavior-sensitive changes and small refactors."
=======
    assert enrichment.guidance.next_step in NEXT_STEP_OPTIONS
    assert enrichment.guidance.evidence_note == (
        "Similar cases here were split between behavior-sensitive changes "
        "and small refactors."
>>>>>>> origin/main
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
    assert context.maintenance_distribution == (("cleanup", 1),)


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

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
    assert enrichment.guidance.explanation is None
    assert enrichment.guidance.next_step is None
    assert enrichment.guidance.evidence_note == (
        "Retrieved historical matches clustered around the same file path and usually disappeared "
        "during later small refactors."
    )


def test_issue_enricher_skips_llm_for_minimal_guidance(
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

    class CountingVerbalizer:
        def __init__(self) -> None:
            self.calls = 0

        def rewrite(self, issue: SonarIssue, guidance: object, historical_context: object) -> object:
            self.calls += 1
            return guidance

    verbalizer = CountingVerbalizer()
    enricher = IssueEnricher(
        dataset_path=dataset_path,
        guidance_verbalizer=verbalizer,
    )

    enrichment = enricher.enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
<<<<<<< HEAD
    assert verbalizer.calls == 0
=======
    assert enrichment.guidance.explanation is None
    assert enrichment.guidance.next_step is None
    assert enrichment.guidance.evidence_note == (
        "In a small set of similar cases, developers leaned toward "
        "small refactors."
    )
>>>>>>> origin/main


def test_issue_enricher_skips_llm_for_minimal_guidance(
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

    class CountingVerbalizer:
        def __init__(self) -> None:
            self.calls = 0

        def rewrite(self, issue: SonarIssue, guidance: object, historical_context: object) -> object:
            self.calls += 1
            return guidance

    verbalizer = CountingVerbalizer()
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
        guidance_verbalizer=verbalizer,
    )

    enrichment = enricher.enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.level is GuidanceLevel.MINIMAL
    assert verbalizer.calls == 0


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

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
<<<<<<< HEAD
        "Retrieved historical matches clustered around the same file path and usually disappeared "
        "during later small refactors."
=======
        "Similar cases here were usually small refactors."
>>>>>>> origin/main
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
    assert enrichment.guidance.evidence_note == (
<<<<<<< HEAD
        "Retrieved historical matches clustered around the same file path and were split between "
        "behavior-sensitive changes and small refactors."
=======
        "Similar cases here were split between behavior-sensitive changes "
        "and small refactors."
>>>>>>> origin/main
    )


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

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
        "Retrieved historical matches clustered around the same file path and usually ended up "
        "resolved in code."
    )


def test_lightweight_llm_verbalizer_rewrites_existing_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    captured_request: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"{\\"explanation\\":\\"Check whether this branch difference is intentional.\\",\\"evidence_note\\":\\"Similar local cases were usually handled as cleanup.\\"}"}]}}]}'
            )

    def fake_urlopen(http_request: object, **_kwargs: object) -> FakeResponse:
        captured_request["url"] = getattr(http_request, "full_url")
        captured_request["headers"] = dict(getattr(http_request, "headers"))
        captured_request["body"] = getattr(http_request, "data")
        return FakeResponse()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    enrichment = IssueEnricher(
        dataset_path=Path("missing.csv"),
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
            tags=("suspicious",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.explanation == "Check whether this branch difference is intentional."
    assert enrichment.guidance.evidence_note is None
    assert captured_request["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    headers = captured_request["headers"]
    assert isinstance(headers, dict)
    assert headers["Content-type"] == "application/json"
    assert headers["X-goog-api-key"] == "secret"
    request_body = captured_request["body"]
    assert isinstance(request_body, bytes)
    parsed_body = json.loads(request_body.decode("utf-8"))
    assert parsed_body["contents"][0]["role"] == "user"
    assert parsed_body["generationConfig"]["responseMimeType"] == "application/json"
    assert parsed_body["generationConfig"]["maxOutputTokens"] == 160
    request_text = parsed_body["contents"][0]["parts"][0]["text"]
    request_facts = json.loads(request_text)
    assert request_facts["review_goal"] == (
        "Help the reviewer decide whether the warning may reflect a behavior change risk."
    )
    assert request_facts["first_check"] in (
        "Verify the surrounding logic before changing the flagged code path.",
        "Check the surrounding logic to confirm the current behavior is really intended.",
        "Validate the code path against the expected behavior before changing it.",
        "Review the flagged logic path against the expected behavior before editing it.",
    )
    assert request_facts["rewrite_targets"]["explanation"] in (
        "This may affect runtime behavior, so verify the intended outcome before editing it.",
        "Review this path carefully before changing it because the current behavior may be intentional.",
        "Validate the expected behavior here before rewriting the code around it.",
        "Check what behavior this code is preserving before you refactor it.",
    )
    assert request_facts["rewrite_targets"]["evidence_note"] is None


def test_lightweight_llm_verbalizer_recovers_json_wrapped_in_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"Here is the rewritten JSON:\\n```json\\n{\\"explanation\\":\\"Validate whether the branch difference is intentional.\\",\\"evidence_note\\":\\"Similar local cases were often cleanup-oriented.\\"}\\n```"}]}}]}'
            )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    enrichment = IssueEnricher(
        dataset_path=Path("missing.csv"),
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm-fallback",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
            tags=("suspicious",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.explanation == "Validate whether the branch difference is intentional."
    assert enrichment.guidance.evidence_note is None


def test_lightweight_llm_verbalizer_rejects_overconfident_history_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"{\\"evidence_note\\":\\"Similar cases definitely require cleanup.\\"}"}]}}]}'
            )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

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

    enrichment = IssueEnricher(
        dataset_path=dataset_path,
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm-guardrail",
            rule="python:S3923",
            severity="MAJOR",
            message="Sonar wording changed for this rule.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
        "Retrieved historical matches clustered around the same file path and were split between "
        "behavior-sensitive changes and nearby follow-up changes."
    )


def test_lightweight_llm_verbalizer_skips_empty_rewrite_targets() -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )
    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        next_step="Check the surrounding logic first.",
    )

    rewritten = verbalizer.rewrite(
        _issue(),
        guidance,
        historical_context=None,
    )

    assert rewritten == guidance


def test_lightweight_llm_verbalizer_falls_back_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )
    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        explanation="Check whether the branch difference is intentional.",
        evidence_note="Historically similar cases usually disappeared during later small refactors.",
    )

    def fail_urlopen(*_args: object, **_kwargs: object) -> object:
        raise error.URLError("network timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    rewritten = verbalizer.rewrite(
        _issue(),
        guidance,
        historical_context=None,
    )

    assert rewritten == guidance


def test_lightweight_llm_verbalizer_supports_openai_compatible_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://llm.example/v1/chat/completions/",
            api_key="secret",
            model="gpt-4o-mini",
        )
    )
    captured_request: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"explanation\\":\\"Review the branch behavior first.\\"}"}}]}'
            )

    def fake_urlopen(http_request: object, **_kwargs: object) -> FakeResponse:
        captured_request["url"] = getattr(http_request, "full_url")
        captured_request["headers"] = dict(getattr(http_request, "headers"))
        captured_request["body"] = getattr(http_request, "data")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        explanation="Check whether the branch difference is intentional.",
        evidence_note=None,
    )
    rewritten = verbalizer.rewrite(
        SonarIssue(
            key="openai-issue",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
        ),
        guidance,
        historical_context=None,
    )

    assert rewritten.explanation == "Review the branch behavior first."
    assert captured_request["url"] == "https://llm.example/v1/chat/completions"
    headers = captured_request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-type"] == "application/json"
    request_body = captured_request["body"]
    assert isinstance(request_body, bytes)
    parsed_body = json.loads(request_body.decode("utf-8"))
    assert parsed_body["model"] == "gpt-4o-mini"
    assert parsed_body["messages"][0]["role"] == "system"


def test_lightweight_llm_verbalizer_helper_branches() -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    persistent_history = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
        dominant_disposition="persistent",
        dominant_disposition_share=0.6667,
        disposition_distribution=(("persistent", 4), ("resolved", 2)),
    )
    assert (
        verbalizer._review_goal(
            SonarIssue(
                key="issue-persistent",
                rule="python:S9999",
                severity="MAJOR",
                message="Potential issue",
                location=IssueLocation(path="src/app.py", line=10),
                issue_type="CODE_SMELL",
            ),
            DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                explanation="Check whether the branch difference is intentional.",
            ),
            persistent_history,
        )
        == (
            "Help the reviewer judge whether this debt tends to linger in this area "
            "and whether it is worth paying down now."
        )
    )
    assert verbalizer._request_url() == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    assert verbalizer._extract_json_object("no json here") is None
    assert verbalizer._response_preview("x " * 200).endswith("...")
    with pytest.raises(TypeError, match="Expected text content"):
        verbalizer._parse_json_text({"not": "text"})
    with pytest.raises(json.JSONDecodeError):
        verbalizer._parse_json_text("no json here")
    assert (
        verbalizer._pick_rewrite(
            {"explanation": "   "},
            "explanation",
            "Check whether the branch difference is intentional.",
        )
        == "Check whether the branch difference is intentional."
    )
    assert (
        verbalizer._pick_rewrite(
            {"explanation": "Sonar says to simplify the conditional."},
            "explanation",
            "Check whether the branch difference is intentional.",
        )
        == "Check whether the branch difference is intentional."
    )
    assert (
        verbalizer._pick_rewrite(
            {"evidence_note": "Similar cases required cleanup."},
            "evidence_note",
            "Historically similar cases usually disappeared during later small refactors.",
        )
        == "Historically similar cases usually disappeared during later small refactors."
    )


def test_issue_enricher_helper_branches(tmp_path: Path) -> None:
    enricher = IssueEnricher(dataset_path=tmp_path / "missing.csv")

    assert enricher._issue_pattern(
        SonarIssue(
            key="dup-literal",
            rule="python:S1",
            severity="MINOR",
            message='Define a constant instead of duplicating this literal "x".',
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="CODE_SMELL",
        )
    ) == "duplicated_literal"
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
    ) is None
    assert IssueEnricher._is_split_distribution(
        (("cleanup", 1), ("behavior", 1)),
        sample_size=0,
    ) is False


def test_issue_enricher_adds_direct_guidance_for_loop_variable_capture(
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
    assert enrichment.guidance.explanation in (
        "Capture `prefix` when the lambda is created, otherwise later loop iterations can change the value it sees here.",
        "Bind `prefix` at lambda creation time so this closure does not pick up a later loop value.",
        "This lambda should capture the current `prefix` value explicitly, or a later loop iteration may change what it reads.",
        "Make the lambda bind the current `prefix` value instead of relying on the loop variable after it changes.",
    )
    assert enrichment.guidance.next_step in (
        "Pass `prefix` into the lambda as a default argument, or wrap the lambda in a helper that binds the current value.",
        "Add `prefix` as a default argument to the parent lambda so each iteration keeps its own value.",
        "Bind `prefix` explicitly in the lambda signature instead of reading the loop variable after it changes.",
        "Capture the current `prefix` value through a default argument or helper function before the next iteration runs.",
    )


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
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=dataset_path,
    )

    enrichment = enricher.enrich(_issue())

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
        "In a small set of similar cases, developers leaned toward "
        "resolved in code."
    )


def test_lightweight_llm_verbalizer_rewrites_existing_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    captured_request: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"{\\"explanation\\":\\"Check whether this branch difference is intentional.\\",\\"evidence_note\\":\\"Similar local cases were usually handled as cleanup.\\"}"}]}}]}'
            )

    def fake_urlopen(http_request: object, **_kwargs: object) -> FakeResponse:
        captured_request["url"] = getattr(http_request, "full_url")
        captured_request["headers"] = dict(getattr(http_request, "headers"))
        captured_request["body"] = getattr(http_request, "data")
        return FakeResponse()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    enrichment = IssueEnricher(
        model_path=Path("missing.joblib"),
        dataset_path=Path("missing.csv"),
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
            tags=("suspicious",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.explanation == "Check whether this branch difference is intentional."
    assert enrichment.guidance.evidence_note is None
    assert captured_request["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    headers = captured_request["headers"]
    assert isinstance(headers, dict)
    assert headers["Content-type"] == "application/json"
    assert headers["X-goog-api-key"] == "secret"
    request_body = captured_request["body"]
    assert isinstance(request_body, bytes)
    parsed_body = json.loads(request_body.decode("utf-8"))
    assert parsed_body["contents"][0]["role"] == "user"
    assert parsed_body["generationConfig"]["responseMimeType"] == "application/json"
    assert parsed_body["generationConfig"]["maxOutputTokens"] == 160
    request_text = parsed_body["contents"][0]["parts"][0]["text"]
    request_facts = json.loads(request_text)
    assert request_facts["review_goal"] == (
        "Help the reviewer decide whether the warning may reflect a behavior change risk."
    )
    assert request_facts["first_check"] in (
        "Verify the surrounding logic before changing the flagged code path.",
        "Check the surrounding logic to confirm the current behavior is really intended.",
        "Validate the code path against the expected behavior before changing it.",
        "Review the flagged logic path against the expected behavior before editing it.",
    )
    assert request_facts["rewrite_targets"]["explanation"] in (
        "Treat this as behavior-sensitive: changing it may alter how the code runs.",
        "This change is worth reviewing carefully because it can affect runtime behavior.",
        "Handle this as a logic concern, not as a mechanical rewrite.",
        "Check the intended behavior before simplifying this code path.",
        "This may affect runtime behavior, so verify the intended outcome before editing it.",
        "Review this path carefully before changing it because the current behavior may be intentional.",
        "Validate the expected behavior here before rewriting the code around it.",
        "Check what behavior this code is preserving before you refactor it.",
    )
    assert request_facts["rewrite_targets"]["evidence_note"] is None


def test_lightweight_llm_verbalizer_recovers_json_wrapped_in_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"Here is the rewritten JSON:\\n```json\\n{\\"explanation\\":\\"Validate whether the branch difference is intentional.\\",\\"evidence_note\\":\\"Similar local cases were often cleanup-oriented.\\"}\\n```"}]}}]}'
            )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    enrichment = IssueEnricher(
        model_path=Path("missing.joblib"),
        dataset_path=Path("missing.csv"),
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm-fallback",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
            tags=("suspicious",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.explanation == "Validate whether the branch difference is intentional."
    assert enrichment.guidance.evidence_note is None


def test_lightweight_llm_verbalizer_rejects_overconfident_history_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"candidates":[{"content":{"parts":[{"text":"{\\"evidence_note\\":\\"Similar cases definitely require cleanup.\\"}"}]}}]}'
            )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

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

    enrichment = IssueEnricher(
        model_path=Path("missing.joblib"),
        dataset_path=dataset_path,
        guidance_verbalizer=verbalizer,
    ).enrich(
        SonarIssue(
            key="issue-llm-guardrail",
            rule="python:S3923",
            severity="MAJOR",
            message="Sonar wording changed for this rule.",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="CODE_SMELL",
            tags=("design",),
        )
    )

    assert enrichment is not None
    assert enrichment.guidance.evidence_note == (
        "Similar cases here were split between behavior-sensitive changes "
        "and nearby follow-up changes."
    )


def test_lightweight_llm_verbalizer_skips_empty_rewrite_targets() -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )
    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        next_step="Check the surrounding logic first.",
    )

    rewritten = verbalizer.rewrite(
        _issue(),
        guidance,
        historical_context=None,
    )

    assert rewritten == guidance


def test_lightweight_llm_verbalizer_falls_back_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )
    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        explanation="Check whether the branch difference is intentional.",
        evidence_note="Similar cases here were often small refactors.",
    )

    def fail_urlopen(*_args: object, **_kwargs: object) -> object:
        raise error.URLError("network timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    rewritten = verbalizer.rewrite(
        _issue(),
        guidance,
        historical_context=None,
    )

    assert rewritten == guidance


def test_lightweight_llm_verbalizer_supports_openai_compatible_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://llm.example/v1/chat/completions/",
            api_key="secret",
            model="gpt-4o-mini",
        )
    )
    captured_request: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"explanation\\":\\"Review the branch behavior first.\\"}"}}]}'
            )

    def fake_urlopen(http_request: object, **_kwargs: object) -> FakeResponse:
        captured_request["url"] = getattr(http_request, "full_url")
        captured_request["headers"] = dict(getattr(http_request, "headers"))
        captured_request["body"] = getattr(http_request, "data")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    guidance = DeveloperGuidance(
        level=GuidanceLevel.DETAILED,
        explanation="Check whether the branch difference is intentional.",
        evidence_note=None,
    )
    rewritten = verbalizer.rewrite(
        SonarIssue(
            key="openai-issue",
            rule="python:S9999",
            severity="CRITICAL",
            message="Possible broken logic path",
            location=IssueLocation(path="src/app.py", line=14),
            issue_type="BUG",
        ),
        guidance,
        historical_context=None,
    )

    assert rewritten.explanation == "Review the branch behavior first."
    assert captured_request["url"] == "https://llm.example/v1/chat/completions"
    headers = captured_request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-type"] == "application/json"
    request_body = captured_request["body"]
    assert isinstance(request_body, bytes)
    parsed_body = json.loads(request_body.decode("utf-8"))
    assert parsed_body["model"] == "gpt-4o-mini"
    assert parsed_body["messages"][0]["role"] == "system"


def test_lightweight_llm_verbalizer_helper_branches() -> None:
    verbalizer = LightweightLLMGuidanceVerbalizer(
        LLMVerbalizerSettings(
            api_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="secret",
            model="gemini-flash-latest",
        )
    )

    persistent_history = HistoricalContext(
        sample_size=6,
        same_rule_matches=3,
        same_scope_matches=6,
        same_path_family_matches=6,
        strong_match_count=4,
        dominant_maintenance="cleanup",
        dominant_maintenance_share=0.6667,
        maintenance_distribution=(("cleanup", 4), ("behavior", 2)),
        dominant_disposition="persistent",
        dominant_disposition_share=0.6667,
        disposition_distribution=(("persistent", 4), ("resolved", 2)),
    )
    assert (
        verbalizer._review_goal(
            SonarIssue(
                key="issue-persistent",
                rule="python:S9999",
                severity="MAJOR",
                message="Potential issue",
                location=IssueLocation(path="src/app.py", line=10),
                issue_type="CODE_SMELL",
            ),
            DeveloperGuidance(
                level=GuidanceLevel.CONTEXTUAL,
                explanation="Check whether the branch difference is intentional.",
            ),
            persistent_history,
        )
        == "Help the reviewer decide whether this warning should be addressed now or safely deferred."
    )
    assert verbalizer._request_url() == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    assert verbalizer._extract_json_object("no json here") is None
    assert verbalizer._response_preview("x " * 200).endswith("...")
    with pytest.raises(TypeError, match="Expected text content"):
        verbalizer._parse_json_text({"not": "text"})
    with pytest.raises(json.JSONDecodeError):
        verbalizer._parse_json_text("no json here")
    assert (
        verbalizer._pick_rewrite(
            {"explanation": "   "},
            "explanation",
            "Check whether the branch difference is intentional.",
        )
        == "Check whether the branch difference is intentional."
    )
    assert (
        verbalizer._pick_rewrite(
            {"explanation": "Sonar says to simplify the conditional."},
            "explanation",
            "Check whether the branch difference is intentional.",
        )
        == "Check whether the branch difference is intentional."
    )
    assert (
        verbalizer._pick_rewrite(
            {"evidence_note": "Similar cases required cleanup."},
            "evidence_note",
            "Similar cases here were often small refactors.",
        )
        == "Similar cases here were often small refactors."
    )


def test_issue_enricher_helper_branches(tmp_path: Path) -> None:
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=tmp_path / "missing.csv",
    )

    assert enricher._issue_pattern(
        SonarIssue(
            key="dup-literal",
            rule="python:S1",
            severity="MINOR",
            message='Define a constant instead of duplicating this literal "x".',
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="CODE_SMELL",
        )
    ) == "duplicated_literal"
    assert enricher._issue_kind(
        SonarIssue(
            key="bug-kind",
            rule="python:S2",
            severity="MAJOR",
            message="Potential wrong behavior",
            location=IssueLocation(path="src/app.py", line=10),
            issue_type="BUG",
        )
    ) == "correctness"
    assert enricher._utility_kind(None, "general") == "cleanup"
    assert enricher._utility_kind(
        HistoricalContext(
            sample_size=6,
            same_rule_matches=3,
            same_scope_matches=6,
            same_path_family_matches=6,
            strong_match_count=4,
            dominant_maintenance="supporting",
            dominant_maintenance_share=0.6667,
            maintenance_distribution=(("supporting", 4), ("cleanup", 2)),
        ),
        "general",
    ) == "cleanup"
    assert IssueEnricher._history_note_from_maintenance(
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
    ) is None
    assert (
        IssueEnricher._history_strength_phrase(
            sample_size=8,
            same_rule_matches=3,
            dominant_share=0.65,
        )
        == "similar cases here were often"
    )
    assert IssueEnricher._is_split_distribution(
        (("cleanup", 1), ("behavior", 1)),
        sample_size=0,
    ) is False


def test_issue_enricher_adds_direct_guidance_for_loop_variable_capture(
    tmp_path: Path,
) -> None:
    enricher = IssueEnricher(
        model_path=tmp_path / "missing.joblib",
        dataset_path=tmp_path / "missing.csv",
    )

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
    assert enrichment.guidance.explanation in (
        "Capture `prefix` when the lambda is created, otherwise later loop iterations can change the value it sees here.",
        "Bind `prefix` at lambda creation time so this closure does not pick up a later loop value.",
        "This lambda should capture the current `prefix` value explicitly, or a later loop iteration may change what it reads.",
        "Make the lambda bind the current `prefix` value instead of relying on the loop variable after it changes.",
    )
    assert enrichment.guidance.next_step in (
        "Pass `prefix` into the lambda as a default argument, or wrap the lambda in a helper that binds the current value.",
        "Add `prefix` as a default argument to the parent lambda so each iteration keeps its own value.",
        "Bind `prefix` explicitly in the lambda signature instead of reading the loop variable after it changes.",
        "Capture the current `prefix` value through a default argument or helper function before the next iteration runs.",
    )


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
