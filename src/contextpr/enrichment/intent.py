from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from contextpr.models import SonarIssue

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IntentPrediction:

    label: str
    confidence: float | None = None


class IntentClassifier:

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model: Any | None = None

    @property
    def is_available(self) -> bool:
        return self._model_path.is_file()

    def predict(self, issue: SonarIssue) -> IntentPrediction | None:
        if not self.is_available:
            return None

        model = self._load_model()
        feature_frame = self._build_feature_frame(issue)
        labels = model.predict(feature_frame)
        if len(labels) == 0:
            return None

        label = str(labels[0])
        return IntentPrediction(
            label=label,
            confidence=self._predict_confidence(model, feature_frame),
        )

    def _load_model(self) -> Any:
        if self._model is None:
            logger.info(
                "Loading intent model artifact.",
                extra={"model_path": str(self._model_path)},
            )
            self._model = joblib.load(self._model_path)
        return self._model

    @staticmethod
    def _build_feature_frame(issue: SonarIssue) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "message": issue.message,
                    "rule": issue.rule,
                    "type": issue.issue_type,
                    "clean_code_attribute": issue.clean_code_attribute,
                    "clean_code_attribute_category": issue.clean_code_attribute_category,
                    "severity": issue.severity,
                    "file_extension": Path(issue.location.path).suffix.lower() or "no_extension",
                    "tags": list(issue.tags),
                }
            ]
        )

    @staticmethod
    def _predict_confidence(model: Any, feature_frame: pd.DataFrame) -> float | None:
        if not hasattr(model, "predict_proba"):
            return None

        probabilities = model.predict_proba(feature_frame)
        if len(probabilities) == 0:
            return None

        return round(float(probabilities[0].max()), 4)
