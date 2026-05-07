from __future__ import annotations

import argparse
import json
from pathlib import Path

from joblib import dump
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return BACKEND_ROOT / path


def _load_jsonl(path: Path) -> pd.DataFrame:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"No rows found in {path}")
    return pd.DataFrame(rows)


def _label_from_sentiment(value: object, threshold: float) -> str | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score >= threshold:
        return "up"
    if score <= -threshold:
        return "down"
    return "neutral"


def _prepare_dataset(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    working = df.copy()
    working["label"] = working["sentiment_score"].apply(lambda value: _label_from_sentiment(value, threshold))
    working = working[working["label"].notna()].copy()
    if working.empty:
        raise SystemExit("No labeled rows available after weak-label generation")

    working["text"] = (
        working["title"].fillna("")
        + "\n"
        + working["description"].fillna("")
        + "\n"
        + working["actor1"].fillna("")
        + " "
        + working["actor2"].fillna("")
    ).str.strip()
    working = working[working["text"].str.len() > 0].copy()
    if working.empty:
        raise SystemExit("No text rows available after preprocessing")

    working["event_type"] = working["event_type"].fillna("unknown").astype(str).str.lower()
    working["country"] = working["country"].fillna("unknown").astype(str).str.lower()
    working["provider"] = working["provider"].fillna("unknown").astype(str).str.lower()
    working["sentiment_score"] = pd.to_numeric(working["sentiment_score"], errors="coerce")
    working["num_mentions"] = pd.to_numeric(working["num_mentions"], errors="coerce")
    working["num_articles"] = pd.to_numeric(working["num_articles"], errors="coerce")
    working["num_sources"] = pd.to_numeric(working["num_sources"], errors="coerce")
    working["published_at"] = pd.to_datetime(working["published_at"], errors="coerce", utc=True)
    working["published_hour"] = working["published_at"].dt.hour
    working["published_dow"] = working["published_at"].dt.dayofweek
    return working


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a baseline ShortPulse surrogate on weak labels.")
    parser.add_argument("--dataset", default="tmp/phase2/historical.combined.jsonl")
    parser.add_argument("--output-model", default="tmp/phase4/models/shortpulse_baseline.joblib")
    parser.add_argument("--output-metrics", default="tmp/phase4/models/shortpulse_baseline.metrics.json")
    parser.add_argument("--label-threshold", type=float, default=1.5)
    parser.add_argument("--max-rows", type=int, default=50000)
    args = parser.parse_args()

    dataset_path = _resolve(args.dataset)
    output_model = _resolve(args.output_model)
    output_metrics = _resolve(args.output_metrics)
    output_model.parent.mkdir(parents=True, exist_ok=True)

    raw = _load_jsonl(dataset_path)
    prepared = _prepare_dataset(raw, threshold=args.label_threshold)
    prepared = prepared.sort_values("published_at", na_position="last").head(args.max_rows).reset_index(drop=True)

    if len(prepared) < 100:
        raise SystemExit(f"Not enough rows to train: {len(prepared)}")

    split_index = int(len(prepared) * 0.85)
    train = prepared.iloc[:split_index].copy()
    test = prepared.iloc[split_index:].copy()
    if train["label"].nunique() < 2 or test["label"].nunique() < 2:
        raise SystemExit("Need at least two labels in both train and test splits")

    feature_columns = [
        "text",
        "event_type",
        "country",
        "provider",
        "sentiment_score",
        "num_mentions",
        "num_articles",
        "num_sources",
        "published_hour",
        "published_dow",
    ]

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=60000), "text"),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                ["event_type", "country", "provider"],
            ),
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler(with_mean=False)),
                    ]
                ),
                ["sentiment_score", "num_mentions", "num_articles", "num_sources", "published_hour", "published_dow"],
            ),
        ]
    )

    model = Pipeline(
        steps=[
            ("features", preprocessor),
            ("clf", LogisticRegression(max_iter=500, class_weight="balanced")),
        ]
    )

    model.fit(train[feature_columns], train["label"])
    predictions = model.predict(test[feature_columns])
    accuracy = accuracy_score(test["label"], predictions)
    report = classification_report(test["label"], predictions, output_dict=True, zero_division=0)
    label_distribution = prepared["label"].value_counts(dropna=False).to_dict()

    payload = {
        "model_type": "shortpulse_baseline_sklearn_logreg",
        "labeling": {
            "mode": "weak_sentiment_proxy",
            "threshold": args.label_threshold,
        },
        "features": feature_columns,
        "labels": sorted(str(value) for value in prepared["label"].dropna().unique()),
        "metrics": {
            "accuracy": float(accuracy),
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "total_rows": int(len(prepared)),
            "label_distribution": {str(key): int(value) for key, value in label_distribution.items()},
            "classification_report": report,
        },
        "pipeline": model,
    }
    dump(payload, output_model)

    metrics_payload = {
        "output_model": str(output_model),
        "dataset": str(dataset_path),
        "accuracy": float(accuracy),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "total_rows": int(len(prepared)),
        "label_distribution": {str(key): int(value) for key, value in label_distribution.items()},
        "classification_report": report,
        "labeling": {
            "mode": "weak_sentiment_proxy",
            "threshold": args.label_threshold,
        },
    }
    output_metrics.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")
    print(json.dumps(metrics_payload, ensure_ascii=True))


if __name__ == "__main__":
    main()
