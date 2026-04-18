from __future__ import annotations

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml.features import build_feature_pipeline

RANDOM_STATE = 42


def build_model() -> Pipeline:
    return Pipeline(
        memory=None,
        steps=[
            ("features", build_feature_pipeline()),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=10_000,
                    random_state=RANDOM_STATE,
                    solver="saga",
                ),
            ),
        ]
    )
