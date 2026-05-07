from __future__ import annotations

import argparse
import json
from pathlib import Path

from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score


def _load_jsonl(path: Path, text_field: str, label_field: str) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = str(row.get(text_field) or "").strip()
            label = row.get(label_field)
            if not text or label is None:
                continue
            texts.append(text)
            labels.append(str(label))
    return texts, labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--label-field", default="label")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = root / dataset
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    texts, labels = _load_jsonl(dataset, args.text_field, args.label_field)
    if len(texts) < 20:
        raise SystemExit(f"Not enough rows for training: {len(texts)}")
    if len(set(labels)) < 2:
        raise SystemExit("Need at least two labels to train classifier")

    x_train, x_test, y_train, y_test = train_test_split(texts, labels, test_size=0.15, shuffle=False)

    model = Pipeline(
        steps=[
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=50000)),
            ("clf", LogisticRegression(max_iter=400, class_weight="balanced")),
        ]
    )
    model.fit(x_train, y_train)
    pred = model.predict(x_test)
    acc = accuracy_score(y_test, pred)

    payload = {
        "model_type": "sklearn_tfidf_logreg",
        "text_field": args.text_field,
        "label_field": args.label_field,
        "labels": sorted(set(labels)),
        "metrics": {"accuracy": float(acc), "rows": len(texts)},
        "pipeline": model,
    }
    dump(payload, output)
    print(json.dumps({"output": str(output), "accuracy": float(acc), "rows": len(texts)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
