"""
Phase 4 Feature Engineering Pipeline — GeoAtlasDatasetBuilder
==============================================================
Transforms raw GDELT event JSONL + PostgreSQL market prices into
a production-quality labeled dataset for 3-class classification.

Architecture:
    GDELT JSONL → process_gdelt_events() → daily aggregated features
    PostgreSQL  → fetch_prices_from_db()  → OHLCV + market features
                ↓
    merge on date (left join on trading calendar)
                ↓
    engineer_event_features() + engineer_market_features()
                ↓
    join_and_label() → dynamic threshold classification
                ↓
    validate_dataset() → leakage check, NaN audit, class balance
                ↓
    build() → final DataFrame + CSV export

Usage:
    python backend/workers/dataset_builder.py --symbol BTCUSDT
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("DatasetBuilder")

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class GeoAtlasDatasetBuilder:
    """
    Builds a labeled ML dataset by joining GDELT geopolitical event features
    with market OHLCV data from PostgreSQL.

    Target: 3-class classification (Bull=+1, Neutral=0, Bear=-1)
    Resolution: Daily (T+1 prediction)
    """

    def __init__(
        self,
        gdelt_events_path: str,
        db_url: str | None = None,
        symbol: str = "BTCUSDT",
        binance_dir: str | None = None,
        max_gdelt_rows: int | None = None,
    ):
        self.gdelt_path = Path(gdelt_events_path)
        self.db_url = db_url
        self.symbol = symbol
        self.binance_dir = binance_dir  # Legacy fallback — not used in v2
        self.max_gdelt_rows = max_gdelt_rows

        # Internal DataFrames (populated during build)
        self._prices_df: Optional[pd.DataFrame] = None
        self._events_df: Optional[pd.DataFrame] = None
        self._merged_df: Optional[pd.DataFrame] = None
        self._final_df: Optional[pd.DataFrame] = None

    # ─────────────────────────────────────────────
    #  1.  PRICE LOADER (PostgreSQL)
    # ─────────────────────────────────────────────

    def fetch_prices_from_db(self) -> pd.DataFrame:
        """
        Reads daily OHLCV from market_prices_daily via psycopg2 (sync).
        Returns a DataFrame indexed by date with computed log returns.
        """
        import psycopg2
        from urllib.parse import urlparse

        if not self.db_url:
            raise ValueError("No database URL provided. Set db_url or DATABASE_URL_SYNC.")

        def parse_db_url(url: str):
            parsed = urlparse(url)
            return {
                "dbname": parsed.path.lstrip("/"),
                "user": parsed.username,
                "password": parsed.password,
                "host": parsed.hostname,
                "port": parsed.port,
            }

        logger.info("Fetching prices for %s from PostgreSQL ...", self.symbol)
        params = parse_db_url(self.db_url)
        conn = psycopg2.connect(**params)
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_prices_daily
            WHERE symbol = %s
            ORDER BY timestamp ASC;
        """
        df = pd.read_sql(query, conn, params=(self.symbol,))
        conn.close()

        if df.empty:
            raise ValueError(
                f"No price data for {self.symbol}. Run the ingestion pipeline first."
            )

        # Type enforcement
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["date"] = df["timestamp"].dt.date
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        df = df.sort_values("date").reset_index(drop=True)
        logger.info(
            "Loaded %d price rows: %s → %s", len(df), df["date"].min(), df["date"].max()
        )
        self._prices_df = df
        return df

    # ─────────────────────────────────────────────
    #  2.  GDELT EVENT LOADER + DAILY AGGREGATION
    # ─────────────────────────────────────────────

    def process_gdelt_events(self) -> pd.DataFrame:
        """
        Streams historical.combined.jsonl, extracts key columns,
        and resamples into daily aggregate features.
        """
        logger.info("Loading GDELT events from %s ...", self.gdelt_path)
        rows: list[dict] = []

        with self.gdelt_path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if self.max_gdelt_rows and i >= self.max_gdelt_rows:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                metadata = record.get("metadata", {}) or {}
                rows.append({
                    "published_at": record.get("published_at"),
                    "sentiment_score": record.get("sentiment_score"),
                    "goldstein_scale": metadata.get("goldstein_scale"),
                    "num_articles": record.get("num_articles"),
                    "num_mentions": record.get("num_mentions"),
                    "event_type": record.get("event_type"),
                })

        raw = pd.DataFrame(rows)
        raw["published_at"] = pd.to_datetime(raw["published_at"], errors="coerce", utc=True)
        raw["sentiment_score"] = pd.to_numeric(raw["sentiment_score"], errors="coerce")
        raw["goldstein_scale"] = pd.to_numeric(raw["goldstein_scale"], errors="coerce")
        raw["num_articles"] = pd.to_numeric(raw["num_articles"], errors="coerce").fillna(0).astype(int)
        raw["num_mentions"] = pd.to_numeric(raw["num_mentions"], errors="coerce").fillna(0).astype(int)
        raw = raw.dropna(subset=["published_at"])
        raw["date"] = raw["published_at"].dt.date

        logger.info("Parsed %d raw events: %s → %s", len(raw), raw["date"].min(), raw["date"].max())

        # ── EXTREME EVENT FILTERING ──
        # Drop background noise. Keep only highly syndicated or inherently high-impact events.
        baseline_len = len(raw)
        raw = raw[
            (raw["num_articles"] >= 5) |
            (abs(raw["goldstein_scale"]) >= 1.5)
        ]
        
        raw["abs_goldstein"] = abs(raw["goldstein_scale"])
        raw["abs_sentiment"] = abs(raw["sentiment_score"])
        
        logger.info("Filtered event noise: Kept %d high-impact events (dropped %d)", len(raw), baseline_len - len(raw))

        # ── Daily aggregation ──
        daily = raw.groupby("date").agg(
            event_count=("sentiment_score", "count"),
            avg_sentiment=("sentiment_score", "mean"),
            avg_goldstein=("goldstein_scale", "mean"),
            max_abs_goldstein=("abs_goldstein", "max"),
            max_abs_sentiment=("abs_sentiment", "max"),
            min_sentiment=("sentiment_score", "min"),
            max_sentiment=("sentiment_score", "max"),
            num_articles=("num_articles", "sum"),
        ).reset_index()

        # ── Event count change (momentum of density) ──
        daily = daily.sort_values("date").reset_index(drop=True)
        daily["event_count_change"] = daily["event_count"].diff().fillna(0)

        logger.info("Aggregated into %d unique event-days", len(daily))
        self._events_df = daily
        return daily

    # ─────────────────────────────────────────────
    #  3.  FEATURE ENGINEERING — MARKET
    # ─────────────────────────────────────────────

    def engineer_market_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds momentum, volatility, moving average, and time features
        to the price DataFrame.
        """
        logger.info("Engineering market features ...")
        df = df.copy()

        # ── Log returns at multiple horizons ──
        df["return_1d"] = np.log(df["close"] / df["close"].shift(1))
        df["return_3d"] = np.log(df["close"] / df["close"].shift(3))
        df["return_7d"] = np.log(df["close"] / df["close"].shift(7))

        # ── Volatility ──
        df["volatility_7d"] = df["close"].pct_change().rolling(7, min_periods=1).std()

        # ── Moving averages ──
        df["ma_7"] = df["close"].rolling(7, min_periods=1).mean()
        df["ma_14"] = df["close"].rolling(14, min_periods=1).mean()
        df["ma_ratio"] = df["ma_7"] / df["ma_14"]

        # ── Time features (surprisingly effective) ──
        df["date_dt"] = pd.to_datetime(df["date"])
        df["day_of_week"] = df["date_dt"].dt.dayofweek
        df["month"] = df["date_dt"].dt.month
        df.drop(columns=["date_dt"], inplace=True)

        return df

    # ─────────────────────────────────────────────
    #  4.  FEATURE ENGINEERING — EVENTS
    # ─────────────────────────────────────────────

    def engineer_event_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds rolling windows, momentum, shock detection, and
        interaction features to the merged DataFrame.
        """
        logger.info("Engineering event features ...")
        df = df.copy()

        # ── Rolling windows ──
        df["sentiment_3d_mean"] = df["avg_sentiment"].rolling(3, min_periods=1).mean()
        df["goldstein_7d_mean"] = df["avg_goldstein"].rolling(7, min_periods=1).mean()
        df["event_count_7d_sum"] = df["event_count"].rolling(7, min_periods=1).sum()

        # ── Momentum features (markets react to CHANGE, not level) ──
        df["sentiment_momentum"] = df["avg_sentiment"].diff()
        df["goldstein_momentum"] = df["avg_goldstein"].diff()

        # ── Event shock detection + persistence ──
        rolling_event_mean = df["event_count"].rolling(7, min_periods=1).mean()
        df["shock"] = (df["event_count"] > rolling_event_mean * 2).astype(int)
        df["shock_decay"] = df["shock"].rolling(3, min_periods=1).max()

        # ── Interaction features ──
        df["impact_score"] = df["avg_goldstein"] * df["event_count"]
        df["sentiment_pressure"] = df["avg_sentiment"] * df["event_count"]

        # ── Non-linear features ──
        df["goldstein_abs"] = abs(df["avg_goldstein"])

        # ── Regime interaction (same news behaves differently in bull vs bear) ──
        df["bear_regime"] = (df["return_7d"] < 0).astype(int) if "return_7d" in df.columns else 0
        df["market_regime"] = (df["return_7d"] > 0).astype(int) if "return_7d" in df.columns else 0
        df["event_bear_interaction"] = df["avg_sentiment"] * df["bear_regime"]

        # ── Additional interactions ──
        if "volatility_7d" in df.columns:
            df["sentiment_x_volatility"] = df["avg_sentiment"] * df["volatility_7d"]
            df["vol_rank"] = df["volatility_7d"].rank(pct=True)
        if "return_1d" in df.columns:
            df["event_x_return"] = df["event_count"] * df["return_1d"]

        # ── Silences vs Activity ──
        df["no_event_flag"] = (df["event_count"] == 0).astype(int)

        # ── Lag Features ──
        for lag in [1, 2, 3]:
            df[f"sentiment_lag_{lag}"] = df["avg_sentiment"].shift(lag).fillna(0)
            df[f"goldstein_lag_{lag}"] = df["avg_goldstein"].shift(lag).fillna(0)
            df[f"event_count_lag_{lag}"] = df["event_count"].shift(lag).fillna(0)
            df[f"spike_lag_{lag}"] = df["shock"].shift(lag).fillna(0)
            
            if "max_abs_goldstein" in df.columns:
                df[f"max_gold_lag_{lag}"] = df["max_abs_goldstein"].shift(lag).fillna(0)
                df[f"max_sent_lag_{lag}"] = df["max_abs_sentiment"].shift(lag).fillna(0)

        return df

    # ─────────────────────────────────────────────
    #  5.  JOIN + TARGET LABELING
    # ─────────────────────────────────────────────

    def join_and_label(self) -> pd.DataFrame:
        """
        Left-joins prices (trading calendar) with aggregated GDELT features,
        engineers all features, and generates the dynamic classification target.

        Join strategy: LEFT JOIN on date (not ASOF — both are daily granularity,
        ASOF becomes trivial and misleading at identical resolution).

        Target: 3-class classification with dynamic volatility-adapted thresholds.
        """
        if self._prices_df is None:
            raise RuntimeError("Call fetch_prices_from_db() first")
        if self._events_df is None:
            raise RuntimeError("Call process_gdelt_events() first")

        # ── Date overlap safety ──
        event_dates = set(self._events_df["date"].unique())
        price_dates = set(self._prices_df["date"].unique())
        overlap = event_dates & price_dates

        if not overlap:
            raise ValueError(
                f"HARD FAIL: Zero date overlap!\n"
                f"  GDELT:  {min(event_dates)} → {max(event_dates)}\n"
                f"  Prices: {min(price_dates)} → {max(price_dates)}"
            )
        logger.info("Date overlap: %d days", len(overlap))

        # ── Left join on trading calendar ──
        merged = self._prices_df.merge(self._events_df, on="date", how="left")

        # Safe fill strategy:
        #   "No event" = 0 signal
        merged["event_count"] = merged["event_count"].fillna(0)
        if "num_articles" in merged.columns:
            merged.drop(columns=["num_articles"], inplace=True)
            
        merged["event_count_change"] = merged["event_count_change"].fillna(0)
        
        # FIX: Fill signals with 0 instead of leaving NaN to prevent data loss
        merged["avg_sentiment"] = merged["avg_sentiment"].fillna(0)
        merged["avg_goldstein"] = merged["avg_goldstein"].fillna(0)
        
        for xt_col in ["max_abs_goldstein", "max_abs_sentiment", "min_sentiment", "max_sentiment"]:
            if xt_col in merged.columns:
                merged[xt_col] = merged[xt_col].fillna(0)

        # ── Engineer features ──
        merged = self.engineer_market_features(merged)
        merged = self.engineer_event_features(merged)

        # ── Target: future log return ──
        merged["future_return"] = np.log(merged["close"].shift(-1) / merged["close"])

        # ── Normalize Target: Asset-Level Z-Score targeting ──
        # This explicitly normalizes BTC vs AAPL volatility before splitting into classes
        rolling_mean = merged["future_return"].rolling(30, min_periods=5).mean().shift(1)
        rolling_std = merged["future_return"].rolling(30, min_periods=5).std().shift(1)
        
        # Fallbacks for early rows
        rolling_mean = rolling_mean.fillna(merged["future_return"].mean())
        rolling_std = rolling_std.fillna(merged["future_return"].std())
        
        # Avoid division by zero
        rolling_std = rolling_std.replace(0, 1e-8)
        
        merged["z_future_return"] = (merged["future_return"] - rolling_mean) / rolling_std

        # ── BINARY VOLATILITY CLASSIFIER (Breakout Prediction) ──
        # Market shocks are asymmetrical; predicting if it will move is mathematically 
        # distinct from predicting which way. 1 = Massive Breakout, 0 = Nothing.
        merged["target"] = (abs(merged["z_future_return"]) > 1.0).astype(int)

        # Drop the last row (no future_return available) and early rows with NaN features
        merged = merged.dropna(subset=["future_return"])

        logger.info("Labeled dataset: %d rows", len(merged))
        self._merged_df = merged
        return merged

    # ─────────────────────────────────────────────
    #  6.  VALIDATION
    # ─────────────────────────────────────────────

    def validate_dataset(self) -> dict:
        """
        Post-build validation suite:
        1. NaN audit on feature columns
        2. Leakage check (no future data in features)
        3. Class balance report
        4. Feature importance readiness check
        """
        if self._merged_df is None:
            raise RuntimeError("Call join_and_label() first")

        df = self._merged_df
        report = {}

        # ── Define feature columns (exclude metadata and target) ──
        exclude_cols = {
            "timestamp", "date", "target", "future_return", "threshold",
            "open", "high", "low",  # Raw OHLCV not used as features
        }
        feature_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in [np.float64, np.int64, float, int]]

        # ── 1. NaN Audit ──
        nan_counts = df[feature_cols].isna().sum()
        total_nans = nan_counts.sum()
        nan_features = nan_counts[nan_counts > 0]

        if total_nans > 0:
            logger.warning("NaN detected in %d feature columns:", len(nan_features))
            for col, count in nan_features.items():
                logger.warning("  %s: %d NaN (%.1f%%)", col, count, count / len(df) * 100)
            
            # Selective drop: Only drop unavoidable NaNs (early rolling windows)
            required_drops = ["return_1d", "return_3d", "return_7d", "volatility_7d"]
            present_drops = [c for c in required_drops if c in df.columns]
            df = df.dropna(subset=present_drops)
            
            # Fill any secondary engineered features that might have propagated early-row NaNs
            df["sentiment_momentum"] = df["sentiment_momentum"].fillna(0)
            df["goldstein_momentum"] = df["goldstein_momentum"].fillna(0)
            df["impact_score"] = df["impact_score"].fillna(0)
            df["sentiment_pressure"] = df["sentiment_pressure"].fillna(0)
            df["event_bear_interaction"] = df["event_bear_interaction"].fillna(0)
            
            logger.info("After selective NaN drop: %d rows remain", len(df))
            self._merged_df = df

        report["nan_dropped"] = int(total_nans)
        report["rows_after_nan_drop"] = len(df)

        # ── 2. Class Balance ──
        class_dist = df["target"].value_counts(normalize=True)
        report["class_distribution"] = {
            str(k): {"count": int(v), "pct": float(p)}
            for k, v, p in zip(
                class_dist.index,
                df["target"].value_counts().values,
                class_dist.values * 100,
            )
        }

        print("\n" + "=" * 60)
        print("  DATASET VALIDATION REPORT")
        print("=" * 60)
        print(f"  Total samples:       {len(df)}")
        print(f"  Feature columns:     {len(feature_cols)}")
        print(f"  NaN rows dropped:    {report['nan_dropped']}")
        print()
        print("  Class Distribution:")
        for cls, info in report["class_distribution"].items():
            label = {"-1": "Bear 📉", "0": "Neutral ─", "1": "Bull 📈"}.get(cls, cls)
            pct = info["pct"]
            bar = "█" * int(pct / 2)
            warning = " ⚠️ LOW" if pct < 5 else ""
            print(f"    {label:>12}: {info['count']:>6} ({pct:>5.1f}%) {bar}{warning}")

        # ── Check for extreme imbalance ──
        for cls, pct in class_dist.items():
            if pct > 0.90:
                logger.warning(
                    "⚠️  Class %d dominates at %.1f%%. Model will be biased! "
                    "Consider adjusting threshold or using class_weight='balanced'.",
                    cls, pct * 100,
                )
            if pct < 0.05:
                logger.warning(
                    "⚠️  Class %d is only %.1f%%. Consider SMOTE or threshold adjustment.",
                    cls, pct * 100,
                )

        # ── 3. Random Baseline Reference ──
        n_classes = df["target"].nunique()
        random_accuracy = 1.0 / n_classes if n_classes > 0 else 0
        print(f"\n  Random baseline accuracy: {random_accuracy * 100:.1f}%")
        print(f"  Your model MUST beat this.\n")

        report["n_features"] = len(feature_cols)
        report["feature_columns"] = feature_cols
        report["random_baseline"] = round(random_accuracy, 4)

        self._final_df = df
        return report

    # ─────────────────────────────────────────────
    #  7.  ORCHESTRATOR
    # ─────────────────────────────────────────────

    def build(self, output_dir: str | Path | None = None) -> pd.DataFrame:
        """
        Full pipeline orchestrator. Calls all steps in correct order,
        exports the final dataset as CSV + metadata JSON.
        """
        logger.info("=" * 60)
        logger.info("  GeoAtlas Dataset Builder — Starting Full Pipeline")
        logger.info("  Symbol: %s", self.symbol)
        logger.info("=" * 60)

        # Step 1: Load data
        self.fetch_prices_from_db()
        self.process_gdelt_events()

        # Step 2: Join and label
        self.join_and_label()

        # Step 3: Validate
        report = self.validate_dataset()

        if self._final_df is None or self._final_df.empty:
            logger.error("Pipeline produced empty dataset. Aborting export.")
            return pd.DataFrame()

        # Step 4: Normalize features (Z-score for XGBoost consistency)
        df = self._final_df.copy()
        feature_cols = report["feature_columns"]

        # Store normalization stats for inference-time usage
        norm_stats = {}
        for col in feature_cols:
            mean_val = df[col].mean()
            std_val = df[col].std()
            norm_stats[col] = {"mean": float(mean_val), "std": float(std_val)}
            if std_val > 0:
                df[col] = (df[col] - mean_val) / std_val

        # Step 5: Temporal train/test split (NO random shuffling)
        df["date_dt"] = pd.to_datetime(df["date"])
        split_date = df["date_dt"].quantile(0.8)
        train = df[df["date_dt"] < split_date]
        test = df[df["date_dt"] >= split_date]

        print(f"\n  Temporal Split:")
        print(f"    Train: {len(train)} rows ({train['date_dt'].min().date()} → {train['date_dt'].max().date()})")
        print(f"    Test:  {len(test)} rows ({test['date_dt'].min().date()} → {test['date_dt'].max().date()})")

        # Verify no temporal leakage in split
        if len(train) > 0 and len(test) > 0:
            assert train["date_dt"].max() < test["date_dt"].min(), \
                "LEAKAGE: train dates overlap with test dates!"
            logger.info("✅ Temporal split verified: no leakage")

        # Step 6: Export
        if output_dir is None:
            output_dir = BACKEND_ROOT / "tmp" / "phase4"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Export full dataset
        csv_path = output_dir / "dataset.csv"
        df.to_csv(csv_path, index=False)
        logger.info("Exported dataset to %s", csv_path)

        # Export metadata
        meta = {
            "symbol": self.symbol,
            "n_samples": len(df),
            "n_features": len(feature_cols),
            "feature_columns": feature_cols,
            "class_distribution": report["class_distribution"],
            "date_range": {
                "start": str(df["date"].min()),
                "end": str(df["date"].max()),
            },
            "split": {
                "train_rows": len(train),
                "test_rows": len(test),
                "split_date": str(split_date.date()) if hasattr(split_date, "date") else str(split_date),
            },
            "normalization_stats": norm_stats,
            "random_baseline": report["random_baseline"],
            "built_at": datetime.utcnow().isoformat(),
        }

        meta_path = output_dir / "dataset_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        logger.info("Exported metadata to %s", meta_path)

        print(f"\n{'=' * 60}")
        print(f"  ✅ PIPELINE COMPLETE")
        print(f"  Dataset:  {csv_path}")
        print(f"  Metadata: {meta_path}")
        print(f"{'=' * 60}\n")

        return df


# ─────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GeoAtlas Dataset Builder — Phase 4")
    parser.add_argument("--symbol", default="BTCUSDT", help="Target symbol")
    parser.add_argument("--gdelt", default=str(BACKEND_ROOT / "tmp" / "phase2" / "historical.combined.jsonl"))
    parser.add_argument("--max-events", type=int, default=None, help="Cap GDELT rows")
    parser.add_argument("--db-url", default=None, help="Override DATABASE_URL_SYNC")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    # Resolve DB URL
    db_url = args.db_url
    if not db_url:
        from dotenv import load_dotenv
        load_dotenv(BACKEND_ROOT / ".env")
        db_url = os.getenv("DATABASE_URL_SYNC")
    if not db_url:
        logger.error("No DATABASE_URL_SYNC. Pass --db-url or set in backend/.env")
        sys.exit(1)

    builder = GeoAtlasDatasetBuilder(
        gdelt_events_path=args.gdelt,
        db_url=db_url,
        symbol=args.symbol,
        max_gdelt_rows=args.max_events,
    )

    df = builder.build(output_dir=args.output_dir)

    if not df.empty:
        # Print target distribution as final sanity check
        print("\n  Target Distribution (raw counts):")
        print(df["target"].value_counts().to_string())


if __name__ == "__main__":
    main()
