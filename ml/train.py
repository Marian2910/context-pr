from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from ml.dataset import TARGET_COLUMN, load_dataset
from ml.evaluate import evaluate_model
from ml.model import RANDOM_STATE, build_model


def train_model(df: pd.DataFrame, output_path: str) -> Pipeline:
    dataset = load_dataset(df)
    x = dataset.drop(columns=[TARGET_COLUMN])
    y = dataset[TARGET_COLUMN]

    _print_class_distribution(y)

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        stratify=y,
        random_state=RANDOM_STATE,
    )

    model = build_model()
    model.fit(x_train, y_train)
    evaluate_model(model, x_test, y_test)
    _save_model(model, output_path)
    return model


def _print_class_distribution(labels: pd.Series) -> None:
    print("Class distribution:")
    distribution = labels.value_counts(dropna=False).sort_index()
    for label, count in distribution.items():
        print(f"  {label}: {count}")


def _save_model(model: Pipeline, output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    print(f"\nSaved model to {path}")
