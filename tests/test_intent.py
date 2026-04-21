from pathlib import Path

import numpy as np
import pytest

from contextpr.enrichment.intent import IntentClassifier
from contextpr.models import IssueLocation, SonarIssue


class FakeModel:

    def predict(self, _frame: object) -> list[str]:
        return ["refactor"]

    def predict_proba(self, _frame: object) -> np.ndarray:
        return np.asarray([[0.2, 0.8]])


class EmptyPredictionModel:

    def predict(self, _frame: object) -> list[str]:
        return []


def test_intent_classifier_returns_none_when_artifact_is_missing(tmp_path: Path) -> None:
    classifier = IntentClassifier(tmp_path / "missing.joblib")

    assert classifier.predict(_issue()) is None


def test_intent_classifier_predicts_label_and_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.joblib"
    model_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("contextpr.enrichment.intent.joblib.load", lambda _path: FakeModel())

    prediction = IntentClassifier(model_path).predict(_issue())

    assert prediction is not None
    assert prediction.label == "refactor"
    assert prediction.confidence == 0.8


def test_intent_classifier_returns_none_for_empty_predictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.joblib"
    model_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "contextpr.enrichment.intent.joblib.load",
        lambda _path: EmptyPredictionModel(),
    )

    assert IntentClassifier(model_path).predict(_issue()) is None


def test_intent_classifier_feature_frame_uses_no_extension() -> None:
    frame = IntentClassifier._build_feature_frame(
        SonarIssue(
            key="issue-1",
            rule="python:S1186",
            severity="MAJOR",
            message="Function is empty",
            location=IssueLocation(path="Dockerfile", line=1),
            issue_type="CODE_SMELL",
            tags=("design",),
            clean_code_attribute="COMPLETE",
            clean_code_attribute_category="INTENTIONAL",
        )
    )

    assert frame.loc[0, "file_extension"] == "no_extension"
    assert frame.loc[0, "tags"] == ["design"]


def _issue() -> SonarIssue:
    return SonarIssue(
        key="issue-1",
        rule="python:S1172",
        severity="MINOR",
        message="Remove unused parameter",
        location=IssueLocation(path="src/app.py", line=10),
        issue_type="CODE_SMELL",
        tags=("unused",),
    )
