from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile

import pandas as pd
from joblib import dump
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.pipeline import Pipeline

from modules.predictions.crypto_features import FEATURE_COLUMNS, build_training_frame


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "base_asset_volume",
    "num_trades",
    "taker_buy_volume",
    "taker_buy_base_asset_volume",
    "ignore",
]


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def _read_kline_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if not names:
            return pd.DataFrame()
        with zf.open(names[0]) as handle:
            df = pd.read_csv(
                handle,
                header=None,
                names=KLINE_COLS,
                usecols=["open_time", "open", "high", "low", "close", "volume", "num_trades", "taker_buy_volume"],
            )
    for col in ["open", "high", "low", "close", "volume", "num_trades", "taker_buy_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    return df.dropna(subset=["open_time", "open", "high", "low", "close"])


def _collect_symbol_files(data_root: Path, symbol: str) -> list[Path]:
    monthly = data_root / "monthly" / "klines" / symbol / "1h"
    daily = data_root / "daily" / "klines" / symbol / "1h"
    files: list[Path] = []
    if monthly.exists():
        files.extend(sorted(monthly.glob("*.zip")))
    if daily.exists():
        files.extend(sorted(daily.glob("*.zip")))
    return files


def _discover_symbols(data_root: Path) -> list[str]:
    monthly_dir = data_root / "monthly" / "klines"
    if not monthly_dir.exists():
        return []
    return sorted(d.name for d in monthly_dir.iterdir() if d.is_dir() and (d / "1h").exists())


def _train_symbol(symbol: str, symbol_df: pd.DataFrame, threshold: float) -> tuple[Pipeline, dict]:
    frame = build_training_frame(symbol_df, threshold=threshold)
    if len(frame) < 500:
        raise RuntimeError(f"{symbol}: not enough rows after feature engineering ({len(frame)})")

    split_idx = int(len(frame) * 0.85)
    train = frame.iloc[:split_idx].copy()
    test = frame.iloc[split_idx:].copy()
    if train["label"].nunique() < 2 or test["label"].nunique() < 2:
        raise RuntimeError(f"{symbol}: insufficient class diversity in train/test split")

    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=120,
                    max_depth=14,
                    min_samples_leaf=30,
                    class_weight="balanced_subsample",
                    n_jobs=1,
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit(train[FEATURE_COLUMNS], train["label"])
    preds = model.predict(test[FEATURE_COLUMNS])
    acc = float(accuracy_score(test["label"], preds))
    macro_f1 = float(f1_score(test["label"], preds, average="macro"))
    report = classification_report(test["label"], preds, output_dict=True, zero_division=0)

    metrics = {
        "symbol": symbol,
        "rows_total": int(len(frame)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "label_distribution": {str(k): int(v) for k, v in frame["label"].value_counts().to_dict().items()},
        "accuracy": acc,
        "macro_f1": macro_f1,
        "classification_report": report,
        "latest_open_time": int(frame["open_time"].max()),
    }
    return model, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train realtime crypto direction models from Binance COIN-M klines.")
    parser.add_argument(
        "--data-root",
        default="downloads/binance_cm/raw",
        help="Path to Binance raw dataset root (contains daily/ and monthly/).",
    )
    parser.add_argument(
        "--output-model",
        default="backend/tmp/phase4/models/crypto_realtime_h1.joblib",
        help="Output joblib artifact path.",
    )
    parser.add_argument(
        "--output-metrics",
        default="backend/tmp/phase4/models/crypto_realtime_h1.metrics.json",
        help="Output metrics JSON path.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional explicit symbol list, e.g. BTCUSD_PERP ETHUSD_PERP.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0010,
        help="Absolute return threshold for direction labels (e.g. 0.001 = 0.1%%).",
    )
    args = parser.parse_args()

    data_root = _resolve(args.data_root)
    output_model = _resolve(args.output_model)
    output_metrics = _resolve(args.output_metrics)
    output_model.parent.mkdir(parents=True, exist_ok=True)

    symbols = args.symbols or _discover_symbols(data_root)
    if not symbols:
        raise SystemExit(f"No symbols found under {data_root}")

    artifact = {
        "model_type": "crypto_hgb_direction_v1",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "horizon": "1h",
        "label_threshold": float(args.threshold),
        "feature_columns": FEATURE_COLUMNS,
        "symbols": {},
    }
    metrics_payload = {
        "model_type": artifact["model_type"],
        "trained_at_utc": artifact["trained_at_utc"],
        "horizon": artifact["horizon"],
        "label_threshold": artifact["label_threshold"],
        "symbols": {},
    }

    for symbol in symbols:
        files = _collect_symbol_files(data_root, symbol)
        if not files:
            continue

        pieces = [_read_kline_zip(path) for path in files]
        symbol_df = pd.concat([p for p in pieces if not p.empty], ignore_index=True)
        if symbol_df.empty:
            continue

        symbol_df = symbol_df.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last")
        model, symbol_metrics = _train_symbol(symbol, symbol_df, threshold=args.threshold)
        artifact["symbols"][symbol] = {
            "model": model,
            "metrics": symbol_metrics,
            "features": FEATURE_COLUMNS,
        }
        metrics_payload["symbols"][symbol] = symbol_metrics

    if not artifact["symbols"]:
        raise SystemExit("No models were trained. Check dataset paths and symbols.")

    dump(artifact, output_model)
    output_metrics.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")
    print(json.dumps({"model": str(output_model), "metrics": str(output_metrics), "symbols": list(artifact["symbols"].keys())}))


if __name__ == "__main__":
    main()
