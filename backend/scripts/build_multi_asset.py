#!/usr/bin/env python3
"""
Phase 4.1: Multi-Asset Orchestrator
===================================
Loops the dataset pipeline across multiple assets (Crypto + TradFi),
applies symbol encoding and crypto tagging, and pools the data into
a single matrix for robust XGBoost learning.
"""

import logging
import sys
import os
from pathlib import Path

# Fix Python path resolution before importing local modules
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
import pandas as pd

from backend.workers.dataset_builder import GeoAtlasDatasetBuilder

BACKEND_ROOT = PROJECT_ROOT / "backend"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MultiAssetBuilder")



def main() -> None:
    symbols = ["BTCUSDT", "ETHUSDT", "AAPL", "SPY"]
    dfs = []
    
    # Check if historic GDELT dataset exists
    gdelt_path = BACKEND_ROOT / "tmp" / "phase2" / "historical.combined.jsonl"
    if not gdelt_path.exists():
        logger.error("Dataset missing: %s. Please run earlier pipelines.", gdelt_path)
        sys.exit(1)

    output_dir = BACKEND_ROOT / "tmp" / "phase4"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Safely load the .env file (prioritizing Root over Backend)
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        env_path = BACKEND_ROOT / ".env"
    
    load_dotenv(dotenv_path=env_path)
    
    db_url = os.getenv("DATABASE_URL_SYNC")
    if not db_url:
        logger.error("DATABASE_URL_SYNC is not set. Check your .env file.")
        sys.exit(1)

    for symbol in symbols:
        logger.info("-" * 40)
        logger.info("Building Normalized Dataset for %s", symbol)
        logger.info("-" * 40)
        try:
            builder = GeoAtlasDatasetBuilder(
                symbol=symbol,
                gdelt_events_path=str(gdelt_path),
                db_url=db_url
            )
            # Create a sub-folder to not pollute the global metrics space
            asset_dir = output_dir / "assets" / symbol
            df = builder.build(output_dir=asset_dir)
            
            if not df.empty:
                df["symbol"] = symbol
                dfs.append(df)
            else:
                logger.warning("Yielded empty dataset for %s. Ensure DB has ingestion records.", symbol)
        except Exception as exc:
            logger.error("Failed to build dataset for %s: %s", symbol, exc)
            
    if not dfs:
        logger.error("No data fetched from any asset. Cannot construct master matrix.")
        sys.exit(1)
        
    logger.info("Pooling %d asset dataframes ...", len(dfs))
    master_df = pd.concat(dfs, ignore_index=True)
    
    # ── Temporal Alignment (De-biasing) ──
    # AAPL has market hours; Crypto is 24/7. To prevent structural bias toward crypto 
    # (which would dominate the tree simply by mass), we enforce dual validation.
    common_dates = master_df.groupby("date")["symbol"].nunique()
    valid_dates = common_dates[common_dates >= 2].index
    
    pre_len = len(master_df)
    master_df = master_df[master_df["date"].isin(valid_dates)]
    logger.info("Aligned timeframe: Dropped %d disjointed rows. Final row count: %d", pre_len - len(master_df), len(master_df))
    
    # ── Multi-Asset Metadata Features ──
    # Model should know crypto reacts radically differently to regulatory/liquidity shock than equities
    master_df["is_crypto"] = master_df["symbol"].isin(["BTCUSDT", "ETHUSDT"]).astype(int)
    
    # Target encoding using one-hot (yields struct 'symbol_BTCUSDT', 'symbol_AAPL' etc.)
    master_df = pd.get_dummies(master_df, columns=["symbol"], dtype=int)
    
    export_path = output_dir / "multi_asset_dataset.csv"
    master_df.to_csv(export_path, index=False)
    
    logger.info("=" * 60)
    logger.info("MULTI-ASSET DATASET SUCCESSFULLY CONSTRUCTED")
    logger.info("Path: %s", export_path)
    logger.info("Rows: %d", len(master_df))
    logger.info("Cross-asset signals enabled: %s", [c for c in master_df.columns if "symbol_" in c or "is_crypto" in c])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
