"""
Phase 4 EDA: GDELT Event ↔ Market Price Correlation Analysis
=============================================================
Reads GDELT events from historical.combined.jsonl and market prices
from PostgreSQL (market_prices_daily). Generates lag correlation matrices,
event shock detection, sentiment regime analysis, and distribution plots.

Usage:
    python backend/scripts/eda_market_events.py --symbol BTCUSDT
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Matplotlib backend must be set BEFORE import ──
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("EDA")

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# ─────────────────────────────────────────────
#  1.  DATA LOADERS
# ─────────────────────────────────────────────

def load_gdelt_events(jsonl_path: Path, max_rows: int | None = None) -> pd.DataFrame:
    """
    Stream-reads the GDELT JSONL, extracting only the columns we need.
    Avoids loading full 80 MB into memory as raw dicts.
    """
    logger.info("Loading GDELT events from %s ...", jsonl_path)
    rows: list[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if max_rows and i >= max_rows:
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
                "event_type": record.get("event_type"),
                "sentiment_score": record.get("sentiment_score"),
                "goldstein_scale": metadata.get("goldstein_scale"),
                "num_articles": record.get("num_articles"),
                "num_mentions": record.get("num_mentions"),
                "country": record.get("country"),
            })

    df = pd.DataFrame(rows)
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce")
    df["goldstein_scale"] = pd.to_numeric(df["goldstein_scale"], errors="coerce")
    df["num_articles"] = pd.to_numeric(df["num_articles"], errors="coerce").fillna(0).astype(int)
    df["num_mentions"] = pd.to_numeric(df["num_mentions"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["published_at"])
    df["date"] = df["published_at"].dt.date
    logger.info("Loaded %d GDELT events spanning %s → %s", len(df), df["date"].min(), df["date"].max())
    return df


def load_prices_from_db(symbol: str, db_url: str) -> pd.DataFrame:
    """
    Loads daily OHLCV from PostgreSQL via psycopg2 (sync, read-only).
    """
    import psycopg2
    from urllib.parse import urlparse

    def parse_db_url(url: str):
        parsed = urlparse(url)
        return {
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username,
            "password": parsed.password,
            "host": parsed.hostname,
            "port": parsed.port,
        }

    logger.info("Querying market_prices_daily for %s ...", symbol)
    params = parse_db_url(db_url)
    conn = psycopg2.connect(**params)
    query = """
        SELECT timestamp, open, high, low, close, volume
        FROM market_prices_daily
        WHERE symbol = %s
        ORDER BY timestamp ASC;
    """
    df = pd.read_sql(query, conn, params=(symbol,))
    conn.close()

    if df.empty:
        logger.error("No price data found for %s in market_prices_daily", symbol)
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date

    # Compute daily log returns
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["returns"] = np.log(df["close"] / df["close"].shift(1))

    logger.info("Loaded %d price rows for %s spanning %s → %s",
                len(df), symbol, df["date"].min(), df["date"].max())
    return df


# ─────────────────────────────────────────────
#  2.  DAILY AGGREGATION
# ─────────────────────────────────────────────

def aggregate_events_daily(events_df: pd.DataFrame) -> pd.DataFrame:
    """Resample GDELT events into daily aggregate features."""
    daily = events_df.groupby("date").agg(
        event_count=("sentiment_score", "count"),
        avg_sentiment=("sentiment_score", "mean"),
        avg_goldstein=("goldstein_scale", "mean"),
        total_articles=("num_articles", "sum"),
    ).reset_index()

    logger.info("Aggregated into %d unique event-days", len(daily))
    return daily


# ─────────────────────────────────────────────
#  3.  ANALYSIS SUITE
# ─────────────────────────────────────────────

def lag_correlation_analysis(merged: pd.DataFrame, output_dir: Path) -> None:
    """
    Tests correlation between key GDELT features and market returns
    at multiple lag values [0, 1, 2, 3, 5, 7].
    """
    logger.info("Running lag correlation analysis ...")
    lags = [0, 1, 2, 3, 5, 7]
    event_features = ["avg_sentiment", "avg_goldstein", "event_count"]
    results = {}

    for feature in event_features:
        if feature not in merged.columns:
            continue
            
        correlations = []
        valid_lags = []
        
        for lag in lags:
            series = merged[feature].shift(lag)
            valid = series.notna() & merged["returns"].notna()
            
            valid_sum = valid.sum()
            # print(f"{feature} lag {lag}: valid points = {valid_sum}")
            
            if valid_sum < 10:  # not enough data
                continue
                
            corr = series[valid].corr(merged["returns"][valid])
            
            if pd.notna(corr):
                correlations.append(corr)
                valid_lags.append(lag)

        # Skip empty features
        if len(correlations) == 0:
            continue
            
        results[feature] = (valid_lags, correlations)

    # Plot
    fig, ax = plt.subplots(figsize=(10, 6))
    for feature, (valid_lags, corrs) in results.items():
        ax.plot(valid_lags, corrs, marker="o", linewidth=2, label=feature)
    ax.set_xlabel("Lag (days)", fontsize=12)
    ax.set_ylabel("Pearson Correlation with Returns", fontsize=12)
    ax.set_title("GDELT Feature ↔ Market Return Lag Correlation", fontsize=14, fontweight="bold")
    ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "lag_correlation.png", dpi=150)
    plt.close()

    # Print results table
    print("\n" + "=" * 60)
    print("  LAG CORRELATION MATRIX")
    print("=" * 60)
    header = f"{'Feature':<20}" + "".join(f"{'Lag ' + str(l):>10}" for l in lags)
    print(header)
    print("-" * 60)
    for feature, (valid_lags, corrs) in results.items():
        val_map = dict(zip(valid_lags, corrs))
        row = f"{feature:<20}" + "".join(f"{val_map.get(l, float('nan')):>10.4f}" for l in lags)
        print(row)
    print()


def event_shock_analysis(merged: pd.DataFrame, output_dir: Path) -> None:
    """Detects days where event density exceeds 2× the 7-day rolling mean."""
    logger.info("Running event shock detection ...")
    merged = merged.copy()
    rolling_mean = merged["event_count"].rolling(7, min_periods=1).mean()
    merged["shock"] = (merged["event_count"] > rolling_mean * 2).astype(int)

    n_shocks = merged["shock"].sum()
    logger.info("Detected %d shock days out of %d total", n_shocks, len(merged))

    # Returns on shock vs non-shock days
    shock_returns = merged.loc[merged["shock"] == 1, "returns"].dropna()
    normal_returns = merged.loc[merged["shock"] == 0, "returns"].dropna()

    print("\n" + "=" * 60)
    print("  EVENT SHOCK ANALYSIS")
    print("=" * 60)
    print(f"  Shock days:       {n_shocks}")
    print(f"  Normal days:      {len(merged) - n_shocks}")
    if len(shock_returns) > 0:
        print(f"  Mean return (shock):   {shock_returns.mean():.6f}")
        print(f"  Mean return (normal):  {normal_returns.mean():.6f}")
        print(f"  Std return (shock):    {shock_returns.std():.6f}")
        print(f"  Std return (normal):   {normal_returns.std():.6f}")
    print()

    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    ax1.fill_between(range(len(merged)), merged["event_count"], alpha=0.4, label="Event Count")
    ax1.plot(rolling_mean.values, color="red", linewidth=1.5, label="7d Rolling Mean")
    shock_idx = merged.index[merged["shock"] == 1]
    ax1.scatter(
        [list(merged.index).index(i) for i in shock_idx if i in merged.index],
        merged.loc[shock_idx, "event_count"],
        color="red", s=30, zorder=5, label="Shock"
    )
    ax1.set_ylabel("Event Count")
    ax1.set_title("GDELT Event Density + Shock Detection", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper right")
    ax1.grid(alpha=0.3)

    ax2.plot(merged["returns"].values, color="steelblue", alpha=0.7, linewidth=0.8)
    ax2.set_ylabel("Log Returns")
    ax2.set_xlabel("Trading Day Index")
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "event_shocks.png", dpi=150)
    plt.close()


def sentiment_regime_analysis(merged: pd.DataFrame, output_dir: Path) -> None:
    """Classifies each day into a sentiment regime and compares returns."""
    logger.info("Running sentiment regime analysis ...")
    merged = merged.copy()
    merged["sentiment_regime"] = np.sign(merged["avg_sentiment"]).map({
        1.0: "Positive", -1.0: "Negative", 0.0: "Neutral"
    }).fillna("Neutral")

    regime_stats = merged.groupby("sentiment_regime")["returns"].agg(["mean", "std", "count"])

    print("\n" + "=" * 60)
    print("  SENTIMENT REGIME ANALYSIS")
    print("=" * 60)
    print(regime_stats.to_string())
    print()

    # Box plot
    fig, ax = plt.subplots(figsize=(8, 6))
    regime_order = ["Negative", "Neutral", "Positive"]
    colors = {"Negative": "#e74c3c", "Neutral": "#95a5a6", "Positive": "#27ae60"}
    for regime in regime_order:
        data = merged.loc[merged["sentiment_regime"] == regime, "returns"].dropna()
        if len(data) > 0:
            bp = ax.boxplot(
                data, positions=[regime_order.index(regime)],
                widths=0.5, patch_artist=True,
                boxprops=dict(facecolor=colors[regime], alpha=0.6),
            )
    ax.set_xticks(range(len(regime_order)))
    ax.set_xticklabels(regime_order)
    ax.set_ylabel("Log Returns")
    ax.set_title("Market Returns by Sentiment Regime", fontsize=14, fontweight="bold")
    ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "sentiment_regime.png", dpi=150)
    plt.close()


def feature_correlation_heatmap(merged: pd.DataFrame, output_dir: Path) -> None:
    """Generates a correlation heatmap of all numeric features."""
    logger.info("Generating feature correlation heatmap ...")
    numeric_cols = [
        "event_count", "avg_sentiment", "avg_goldstein",
        "returns", "goldstein_abs", "market_regime",
        "sentiment_x_volatility", "event_x_return"
    ]
    # Add lag features if they exist
    for lag in [1, 2, 3]:
        numeric_cols.extend([f"sentiment_lag_{lag}", f"goldstein_lag_{lag}"])
        
    available = [c for c in numeric_cols if c in merged.columns]
    
    # Calculate correlations
    corr_matrix = merged[available].corr()
    
    # Plot using a larger figure to accommodate more features
    fig, ax = plt.subplots(figsize=(14, 12))
    sns.heatmap(
        corr_matrix,
        annot=True, fmt=".2f", cmap="RdBu_r", center=0,
        square=True, linewidths=0.5, ax=ax,
    )
    ax.set_title("Feature Correlation Matrix", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_dir / "correlation_heatmap.png", dpi=150)
    plt.close()


# ─────────────────────────────────────────────
#  4.  MAIN
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 EDA: GDELT ↔ Market Correlation")
    parser.add_argument("--symbol", default="BTCUSDT", help="Target symbol in market_prices_daily")
    parser.add_argument("--gdelt", default=str(BACKEND_ROOT / "tmp" / "phase2" / "historical.combined.jsonl"))
    parser.add_argument("--max-events", type=int, default=None, help="Cap GDELT rows for faster iteration")
    parser.add_argument("--db-url", default=None, help="Override DATABASE_URL_SYNC from .env")
    args = parser.parse_args()

    # Resolve DB URL
    db_url = args.db_url
    if not db_url:
        from dotenv import load_dotenv
        load_dotenv(BACKEND_ROOT / ".env")
        db_url = os.getenv("DATABASE_URL_SYNC")
    if not db_url:
        logger.error("No DATABASE_URL_SYNC found. Pass --db-url or set in .env")
        sys.exit(1)

    output_dir = BACKEND_ROOT / "tmp" / "phase4" / "eda"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Load ──
    events_raw = load_gdelt_events(Path(args.gdelt), max_rows=args.max_events)
    prices_df = load_prices_from_db(args.symbol, db_url)

    if prices_df.empty:
        logger.error("Cannot proceed: no price data. Run the ingestion pipeline first.")
        sys.exit(1)

    # ── Date overlap safety check ──
    event_dates = set(events_raw["date"].unique())
    price_dates = set(prices_df["date"].unique())
    overlap = event_dates & price_dates

    if not overlap:
        logger.error(
            "HARD FAIL: Zero date overlap between GDELT (%s→%s) and prices (%s→%s)",
            min(event_dates), max(event_dates),
            min(price_dates), max(price_dates),
        )
        sys.exit(1)
    logger.info("Date overlap: %d days (%s → %s)", len(overlap), min(overlap), max(overlap))

    # ── Aggregate events daily ──
    events_daily = aggregate_events_daily(events_raw)

    # ── Merge on trading calendar (left join on price dates) ──
    merged = prices_df.merge(events_daily, on="date", how="left")

    # Safe fill: "No event" = 0 signal
    merged["event_count"] = merged["event_count"].fillna(0)
    if "total_articles" in merged.columns:
        merged.drop(columns=["total_articles"], inplace=True)
        
    merged["avg_sentiment"] = merged["avg_sentiment"].fillna(0)
    merged["avg_goldstein"] = merged["avg_goldstein"].fillna(0)

    # Calculate 7d returns and volatility for regimes & interactions
    merged["return_7d"] = merged["returns"].rolling(7).sum() # simple sum of daily log returns
    merged["volatility_7d"] = merged["returns"].rolling(7).std()

    # Add Non-linear Signals
    merged["goldstein_abs"] = abs(merged["avg_goldstein"])

    # Add Regime / Interaction Features
    merged["market_regime"] = (merged["return_7d"] > 0).astype(int)
    merged["sentiment_x_volatility"] = merged["avg_sentiment"] * merged["volatility_7d"]
    merged["event_x_return"] = merged["event_count"] * merged["returns"]

    # Add Lagged Features
    for lag in [1, 2, 3]:
        merged[f"sentiment_lag_{lag}"] = merged["avg_sentiment"].shift(lag).fillna(0)
        merged[f"goldstein_lag_{lag}"] = merged["avg_goldstein"].shift(lag).fillna(0)

    # Drop rows with no valid daily return
    merged = merged.dropna(subset=["returns", "return_7d", "volatility_7d"])

    logger.info("Merged dataset: %d rows × %d columns", *merged.shape)

    # ── Run analyses ──
    lag_correlation_analysis(merged, output_dir)
    event_shock_analysis(merged, output_dir)
    sentiment_regime_analysis(merged, output_dir)
    feature_correlation_heatmap(merged, output_dir)

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  EDA COMPLETE")
    print("=" * 60)
    print(f"  Symbol:           {args.symbol}")
    print(f"  Price rows:       {len(prices_df)}")
    print(f"  Event rows:       {len(events_raw)}")
    print(f"  Merged rows:      {len(merged)}")
    print(f"  Date overlap:     {len(overlap)} days")
    print(f"  Output saved to:  {output_dir}")
    print()


if __name__ == "__main__":
    main()
