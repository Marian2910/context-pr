"""Intent classification helpers powered by a trained sklearn artifact."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import pandas as pd

from contextpr.models import SonarIssue

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IntentPrediction:
    """Represent a predicted issue intent label."""

    label: str
    confidence: float | None = None


class IntentClassifier:
    """Load a persisted model artifact and predict issue intent labels."""

    def __init__(self, model_path: Path) -> None:
        """Store the path to the persisted sklearn pipeline."""
        self._model_path = model_path
        self._model: Any | None = None

    @property
    def is_available(self) -> bool:
        """Return whether the configured artifact exists on disk."""
        return self._model_path.is_file()

    def predict(self, issue: SonarIssue) -> IntentPrediction | None:
        """Predict a change intent label for a Sonar issue."""
        if not self.is_available:
            return None

        model = self._load_model()
        feature_frame = self._build_feature_frame(issue)
        labels = model.predict(feature_frame)
        if not isinstance(labels, list | tuple) and getattr(labels, "size", 0) == 0:
            return None

        label = str(labels[0])
        confidence = self._predict_confidence(model, feature_frame)
        return IntentPrediction(label=label, confidence=confidence)

    def _load_model(self) -> Any:
        """Load and cache the persisted model artifact."""
        if self._model is None:
            logger.info(
                "Loading intent classification model artifact.",
                extra={"model_path": str(self._model_path)},
            )
            self._model = joblib.load(self._model_path)
        return self._model

    @staticmethod
    def _build_feature_frame(issue: SonarIssue) -> pd.DataFrame:
        """Map a Sonar issue into the feature schema expected by the model."""
        return pd.DataFrame(
            [
                {
                    "message": issue.message,
                    "rule": issue.rule,
                    "type": issue.issue_type,
                    "clean_code_attribute": issue.clean_code_attribute,
                    "clean_code_attribute_category": issue.clean_code_attribute_category,
                    "severity": issue.severity,
                    "file_extension": Path(issue.location.path).suffix.lower(),
                    "tags": list(issue.tags),
                }
            ]
        )

    @staticmethod
    def _predict_confidence(model: Any, feature_frame: pd.DataFrame) -> float | None:
        """Return the top predicted class probability when available."""
        if not hasattr(model, "predict_proba"):
            return None

        probabilities = model.predict_proba(feature_frame)
        if getattr(probabilities, "size", 0) == 0:
            return None

        top_probability = float(probabilities[0].max())
        return round(top_probability, 4)
