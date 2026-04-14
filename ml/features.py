from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, MultiLabelBinarizer, OneHotEncoder

TEXT_COLUMNS = ["message", "rule"]
CATEGORICAL_COLUMNS = [
    "rule",
    "type",
    "clean_code_attribute",
    "clean_code_attribute_category",
    "severity",
    "file_extension",
]


def build_feature_pipeline() -> ColumnTransformer:
    """Build the full sklearn feature pipeline."""
    text_pipeline = Pipeline(
        steps=[
            (
                "combine",
                FunctionTransformer(_combine_text_columns, validate=False),
            ),
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=10_000,
                ),
            ),
        ]
    )
    tags_pipeline = Pipeline(
        steps=[
            (
                "select",
                FunctionTransformer(_select_tags_column, validate=False),
            ),
            ("binarize", MultiLabelBinarizerTransformer()),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("text", text_pipeline, TEXT_COLUMNS),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_COLUMNS,
            ),
            ("tags", tags_pipeline, ["tags"]),
        ]
    )


class MultiLabelBinarizerTransformer(BaseEstimator, TransformerMixin):
    """Wrap ``MultiLabelBinarizer`` for sklearn pipeline use."""

    def __init__(self) -> None:
        """Initialize the underlying multi-label binarizer."""
        self._binarizer = MultiLabelBinarizer()

    def fit(
        self,
        x: pd.DataFrame | pd.Series | np.ndarray,
        y: object = None,
    ) -> MultiLabelBinarizerTransformer:
        """Fit the binarizer on iterable tag values."""
        self._binarizer.fit(_normalize_tag_rows(x))
        self.classes_ = self._binarizer.classes_
        return self

    def transform(
        self,
        x: pd.DataFrame | pd.Series | np.ndarray,
    ) -> np.ndarray:
        """Transform iterable tag values into a binary feature matrix."""
        return self._binarizer.transform(_normalize_tag_rows(x))

    def get_feature_names_out(self, input_features: object = None) -> np.ndarray:
        """Return output feature names."""
        return np.asarray([f"tag__{label}" for label in self.classes_], dtype=object)


def _combine_text_columns(frame: pd.DataFrame) -> np.ndarray:
    """Combine message and rule fields into a single text field."""
    combined = (
        frame["message"].fillna("").astype(str).str.strip()
        + " [RULE] "
        + frame["rule"].fillna("").astype(str).str.strip()
    )
    return combined.to_numpy()


def _select_tags_column(frame: pd.DataFrame) -> np.ndarray:
    """Select the tags column from a single-column frame."""
    return frame.iloc[:, 0].to_numpy()


def _normalize_tag_rows(
    values: pd.DataFrame | pd.Series | np.ndarray,
) -> list[list[str]]:
    """Normalize pipeline input values for multi-label binarization."""
    if isinstance(values, pd.DataFrame):
        raw_rows = values.iloc[:, 0].tolist()
    elif isinstance(values, pd.Series):
        raw_rows = values.tolist()
    else:
        raw_rows = values.tolist()

    normalized_rows: list[list[str]] = []
    for row in raw_rows:
        if isinstance(row, list):
            normalized_rows.append([str(item) for item in row])
        elif isinstance(row, tuple | set):
            normalized_rows.append([str(item) for item in row])
        else:
            normalized_rows.append([])

    return normalized_rows
