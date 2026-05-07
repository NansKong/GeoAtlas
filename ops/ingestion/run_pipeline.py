import time
import os
from dotenv import load_dotenv
from db import upsert_symbols, upsert_market_prices, apply_schema
from universe import get_full_universe
from fetchers import fetch_binance_bulk, fetch_twelvedata_bulk, fetch_polygon_bulk
from cleaner import clean_and_validate

# Point dotenv directly to the backend directory's .env file
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", ".env")
load_dotenv(dotenv_path=env_path)

def get_valid_binance_symbols():
    from binance.client import Client
    import os

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    # If keys are missing, just return empty set to avoid crash, allowing graceful skip
    if not api_key:
        print("[WARNING] BINANCE_API_KEY missing, skipping Binance prep.")
        return set()
        
    client = Client(api_key, api_secret)
    try:
        info = client.get_exchange_info()
        return {s['symbol'] for s in info['symbols']}
    except Exception as e:
        print(f"[ERROR] Failed to fetch Binance exchange info: {e}")
        return set()

VALID_BINANCE = get_valid_binance_symbols()

def to_binance_symbol(symbol):
    candidate = symbol.replace("-USD", "USDT")
    # If it's already in pure crypto format (like BTCUSDT), just return candidate
    if candidate in VALID_BINANCE:
        return candidate
    return None

def retry_failed_symbols(interval="1d"):
    """Robust fallback: Retry any symbols that failed on their original pass"""
    import json
    
    # Retry Binance
    if os.path.exists("failed_binance.json"):
        with open("failed_binance.json", "r") as f:
            failed = json.load(f)
        if failed:
            print(f"\n[RETRY] Attempting {len(failed)} failed Binance symbols...")
            for chunk_data in fetch_binance_bulk(failed, period="2 years ago UTC", interval=interval):
                if chunk_data:
                    upsert_market_prices(clean_and_validate(chunk_data), timeframe="daily")
            # Clear if success (naive approach, can be improved)
            os.remove("failed_binance.json")

    # Retry Polygon via TwelveData Fallback
    if os.path.exists("failed_polygon.json"):
        with open("failed_polygon.json", "r") as f:
            failed = json.load(f)
        if failed:
            print(f"\n[RETRY] Retrying {len(failed)} Polygon failures via TwelveData fallback...")
            for chunk_data in fetch_twelvedata_bulk(failed, interval=interval):
                if chunk_data:
                    upsert_market_prices(clean_and_validate(chunk_data), timeframe="daily")
            os.remove("failed_polygon.json")

    # Retry TwelveData
    if os.path.exists("failed_twelvedata.json"):
        with open("failed_twelvedata.json", "r") as f:
            failed = json.load(f)
        if failed:
            print(f"\n[RETRY] Attempting {len(failed)} failed TwelveData symbols...")
            for chunk_data in fetch_twelvedata_bulk(failed, interval=interval):
                if chunk_data:
                    upsert_market_prices(clean_and_validate(chunk_data), timeframe="daily")
            os.remove("failed_twelvedata.json")

def main():
    print("=== GeoAtlas Data Ingestion Pipeline ===")
    
    # 0. Ensure schema exists
    print("\n[Step 0] Verifying database schema...")
    apply_schema()
    
    # 1. Sync/Load Universe
    print("\n[Step 1] Loading Universe Symbols...")
    universe_symbols = get_full_universe()
    print(f"Upserting {len(universe_symbols)} symbols into database...")
    upsert_symbols(universe_symbols)

    # 2. Extract sources with exact mapping fixes
    raw_binance_symbols = [
        to_binance_symbol(row['symbol']) 
        for row in universe_symbols 
        if row['source'] == 'binance'
    ]
    # Filter out None values from missing pairs
    binance_symbols = [s for s in raw_binance_symbols if s is not None]
    
    polygon_symbols = [row['symbol'] for row in universe_symbols if row['source'] == 'polygon']
    twelvedata_symbols = [row['symbol'] for row in universe_symbols if row['source'] == 'twelvedata']
    
    interval = "1d"
    start_time = time.time()
    
    # --- PHASE 1: Binance (Crypto) ---
    print(f"\n[Phase 1] Fetching Crypto Data (Binance)...")
    if binance_symbols:
        try:
            binance_period = "2 years ago UTC"
            for chunk_data in fetch_binance_bulk(binance_symbols, period=binance_period, interval=interval):
                if chunk_data:
                    cleaned_data = clean_and_validate(chunk_data)
                    upsert_market_prices(cleaned_data, timeframe="daily")
        except Exception as e:
            print(f"[ERROR] Binance fetching failed completely: {e}")
            
    # --- PHASE 2: Polygon (Critical Stocks) ---
    print(f"\n[Phase 2] Fetching Critical Stocks Data (Polygon)...")
    if polygon_symbols:
        try:
            for chunk_data in fetch_polygon_bulk(polygon_symbols, period_days=730, interval=interval):
                if chunk_data:
                    cleaned_data = clean_and_validate(chunk_data)
                    upsert_market_prices(cleaned_data, timeframe="daily")
        except Exception as e:
            print(f"[ERROR] Polygon fetching failed completely: {e}")
            
    # --- PHASE 3: TwelveData (Bulk Stocks) ---
    print(f"\n[Phase 3] Fetching Fallback Stocks Data (TwelveData)...")
    if twelvedata_symbols:
        try:
            for chunk_data in fetch_twelvedata_bulk(twelvedata_symbols, interval=interval):
                if chunk_data:
                    cleaned_data = clean_and_validate(chunk_data)
                    upsert_market_prices(cleaned_data, timeframe="daily")
        except Exception as e:
            print(f"[ERROR] TwelveData fetching failed completely: {e}")
            
    # --- PHASE 4: Retry Pass ---
    print(f"\n[Phase 4] Retrying any failed symbols...")
    retry_failed_symbols(interval)

    end_time = time.time()
    print(f"\n=== Pipeline Completed Successfully in {end_time - start_time:.2f} seconds ===")

if __name__ == "__main__":
    main()
