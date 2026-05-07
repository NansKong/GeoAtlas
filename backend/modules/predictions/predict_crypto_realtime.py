from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from joblib import load
from sqlalchemy import create_engine, text

from modules.predictions.crypto_features import FEATURE_COLUMNS, build_latest_feature_row


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return BACKEND_ROOT / path_str


def _normalize_symbol(ticker: str, known_symbols: set[str]) -> str:
    t = ticker.strip().upper()
    if t in known_symbols:
        return t
    if not t.endswith("_PERP") and f"{t}_PERP" in known_symbols:
        return f"{t}_PERP"
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description="Run realtime crypto direction inference from market_prices table.")
    parser.add_argument("--ticker", required=True, help="Asset ticker in assets table (e.g. BTCUSD_PERP or BTCUSD).")
    parser.add_argument("--database-url", required=True, help="Sync SQLAlchemy DB URL.")
    parser.add_argument("--lookback", type=int, default=500, help="How many latest market rows to fetch.")
    parser.add_argument(
        "--model",
        default="tmp/phase4/models/crypto_realtime_h1.joblib",
        help="Path to trained crypto realtime model artifact.",
    )
    args = parser.parse_args()

    model_path = _resolve(args.model)
    if not model_path.exists():
        raise SystemExit(f"Model artifact not found: {model_path}")

    pack = load(model_path)
    known_symbols = set(pack.get("symbols", {}).keys())
    symbol = _normalize_symbol(args.ticker, known_symbols)
    symbol_pack = pack.get("symbols", {}).get(symbol)
    if not symbol_pack:
        raise SystemExit(f"No model found for symbol '{symbol}'. Available: {sorted(known_symbols)}")

    sql = text(
        """
        SELECT mp.timestamp, mp.open, mp.high, mp.low, mp.close, mp.volume
        FROM market_prices mp
        JOIN assets a ON a.id = mp.asset_id
        WHERE UPPER(a.ticker) = :ticker
        ORDER BY mp.timestamp DESC
        LIMIT :limit
        """
    )
    engine = create_engine(args.database_url)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"ticker": args.ticker.upper(), "limit": int(args.lookback)}).fetchall()

    if len(rows) < 48:
        raise SystemExit(f"Not enough rows for inference: {len(rows)} (need >= 48)")

    df = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    df["open_time"] = (pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 10**6).astype("int64")
    df["num_trades"] = pd.NA
    df["taker_buy_volume"] = pd.NA
    frame = df[["open_time", "open", "high", "low", "close", "volume", "num_trades", "taker_buy_volume"]].copy()

    latest_x = build_latest_feature_row(frame)
    if latest_x.empty:
        raise SystemExit("Failed to build feature row from latest bars.")

    model = symbol_pack["model"]
    pred = str(model.predict(latest_x[FEATURE_COLUMNS])[0])
    conf = None
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(latest_x[FEATURE_COLUMNS])[0]
        classes = list(model.classes_)
        conf = float(proba[classes.index(pred)])

    last_close = float(df["close"].iloc[-1])
    payload = {
        "ticker": args.ticker.upper(),
        "symbol_model": symbol,
        "model_type": pack.get("model_type"),
        "predicted_direction_h1": pred,
        "confidence": conf,
        "last_close": last_close,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
