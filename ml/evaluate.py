from __future__ import annotations

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, precision_recall_fscore_support
from sklearn.pipeline import Pipeline


def evaluate_model(
    model: Pipeline,
    x_test: pd.DataFrame,
    y_test: pd.Series,
) -> dict[str, float]:
    predictions = model.predict(x_test)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test,
        predictions,
        average="macro",
        zero_division=0,
    )
    accuracy = accuracy_score(y_test, predictions)

    metrics = {
        "accuracy": float(accuracy),
        "precision_macro": float(precision),
        "recall_macro": float(recall),
        "f1_macro": float(f1),
    }

    print("Evaluation metrics:")
    for name, value in metrics.items():
        print(f"  {name}: {value:.4f}")

    print("\nClassification report:")
    print(classification_report(y_test, predictions, zero_division=0))

    return metrics
