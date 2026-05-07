import asyncio
import aiohttp
import os
import time
from dotenv import load_dotenv

# Re-use our synchronous DB connection layer logically locked per loop event
from db import upsert_symbols, upsert_market_prices, apply_schema, get_latest_timestamps
from universe import get_full_universe
from cleaner import clean_and_validate

# Async logic
from rate_limiter import polygon_limiter, twelvedata_limiter, binance_limiter
from provider_score import ProviderScorer
from async_fetchers import fetch_binance_async, fetch_polygon_async, fetch_twelvedata_async

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", ".env")
load_dotenv(dotenv_path=env_path)

def get_valid_binance_symbols():
    from binance.client import Client
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key:
        return set()
    try:
        info = Client(api_key, api_secret).get_exchange_info()
        return {s['symbol'] for s in info['symbols']}
    except Exception:
        return set()

VALID_BINANCE = get_valid_binance_symbols()

def to_binance_symbol(symbol):
    cand = symbol.replace("-USD", "USDT")
    if cand in VALID_BINANCE:
        return cand
    return None

async def worker_binance(client, scorer, symbol, interval, latest_ts=None):
    """Encapsulates async fetch + background DB pipeline insert"""
    data = await fetch_binance_async(client, scorer, symbol, interval=interval)
    if data:
        cleaned = await asyncio.to_thread(clean_and_validate, data)
        if cleaned:
            await asyncio.to_thread(upsert_market_prices, cleaned, "daily")
        return True, symbol
    return False, symbol

async def worker_polygon(session, scorer, symbol, interval, latest_ts=None, retries=2):
    for attempt in range(retries):
        data = await fetch_polygon_async(session, scorer, symbol, interval=interval, latest_ts=latest_ts)
        if data:
            cleaned = await asyncio.to_thread(clean_and_validate, data)
            if cleaned:
                await asyncio.to_thread(upsert_market_prices, cleaned, "daily")
            return True, symbol
        # Wait before retry inside the worker
        await asyncio.sleep(2 + attempt * 2)
    return False, symbol

async def worker_twelvedata(session, scorer, symbol, interval, latest_ts=None, retries=2):
    for attempt in range(retries):
        data = await fetch_twelvedata_async(session, scorer, symbol, interval=interval, latest_ts=latest_ts)
        if data:
            cleaned = await asyncio.to_thread(clean_and_validate, data)
            if cleaned:
                await asyncio.to_thread(upsert_market_prices, cleaned, "daily")
            return True, symbol
        await asyncio.sleep(2 + attempt * 2)
    return False, symbol

async def main_async():
    print("=== GeoAtlas Async Ingestion Pipeline Active ===")
    
    print("\n[Step 0] Verifying database schema...")
    apply_schema()
    
    print("\n[Step 1] Loading Universe Symbols...")
    universe_symbols = get_full_universe()
    upsert_symbols(universe_symbols)

    interval = "1d"

    print("\n[Step 1.5] Fetching Latest DB Timestamps (Incremental Cache)...")
    all_syms = [r['symbol'] for r in universe_symbols]
    latest_cache = get_latest_timestamps(all_syms, timeframe=("daily" if interval == "1d" else "hourly"))

    # Scrape configuration
    raw_binance_symbols = [to_binance_symbol(r['symbol']) for r in universe_symbols if r['source'] == 'binance']
    binance_symbols = [s for s in raw_binance_symbols if s is not None]
    polygon_symbols = [r['symbol'] for r in universe_symbols if r['source'] == 'polygon']
    twelvedata_symbols = [r['symbol'] for r in universe_symbols if r['source'] == 'twelvedata']
    
    # Initialize the Scoped Scorer
    scorer = ProviderScorer(failure_threshold=0.5)
    
    start_time = time.time()
    
    # ---------------------------------------------
    # PHASE 1: BINANCE CONCURRENCY 
    # ---------------------------------------------
    failed_binance = []
    if binance_symbols:
        from binance.client import AsyncClient
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")
        
        try:
            client = await AsyncClient.create(api_key, api_secret)
        except Exception as e:
            print(f"[Async] Binance initialization failed: {e}")
            client = None
            
        if client:
            print(f"\n[Phase 1] Launching {len(binance_symbols)} parallel Binance crypto tasks...")
            tasks = [worker_binance(client, scorer, s, interval, latest_ts=latest_cache.get(s)) for s in binance_symbols]
            results = await asyncio.gather(*tasks)
            for success, sym in results:
                if not success:
                    failed_binance.append(sym)
            await client.close_connection()
                
    # ---------------------------------------------
    # PHASE 2 & 3: AIOHTTP PARALLEL CONTEXT
    # ---------------------------------------------
    failed_polygon = []
    failed_twelvedata = []
    
    async with aiohttp.ClientSession() as session:
        # Phase 2: Polygon
        if polygon_symbols:
            print(f"\n[Phase 2] Launching {len(polygon_symbols)} Polygon parallel tasks (Rate Limited Async Bucket)...")
            tasks = [worker_polygon(session, scorer, s, interval, latest_ts=latest_cache.get(s)) for s in polygon_symbols]
            results = await asyncio.gather(*tasks)
            for success, sym in results:
                if not success:
                    failed_polygon.append(sym)
                    
        # Score Tracking Fallback Decision
        if failed_polygon:
            print(f"\n[WARNING] {len(failed_polygon)} Polygon fetches failed.")
            if scorer.should_fallback("polygon"):
                print(f"[RE-ROUTE] Polygon API Score fell below {scorer.failure_threshold*100}%. Dynamically moving entirely to TwelveData.")
                # We can just push all failed ones directly to the twelvedata queue seamlessly
                twelvedata_symbols.extend(failed_polygon)
                failed_polygon = [] # Empty it out
            else:
                print(f"Polygon API Score remains viable. Retrying locally later...")

        # Phase 3: TwelveData (includes natural list + any forced routed failures)
        if twelvedata_symbols:
            print(f"\n[Phase 3] Launching {len(twelvedata_symbols)} TwelveData parallel tasks...")
            tasks = [worker_twelvedata(session, scorer, s, interval, latest_ts=latest_cache.get(s)) for s in twelvedata_symbols]
            results = await asyncio.gather(*tasks)
            for success, sym in results:
                if not success:
                    failed_twelvedata.append(sym)
                    
    # Retries (Very last resort mapped fallback - Batched!)
    if failed_polygon:
        from adapters import adapter
        
        # Pre-filter failed symbols to prevent wasting requests on naturally unsupported ones
        supported_failures = [s for s in failed_polygon if adapter.is_supported_by_twelvedata(s)]
        
        if supported_failures:
            print(f"\n[Phase 4] Forcing {len(supported_failures)} remaining Polygon failures via TwelveData Batches...")
            async with aiohttp.ClientSession() as retry_session:
                tasks = []
                remaining = len(supported_failures)
                
                # Dynamic batch size constraint explicitly bounded by 8 (max efficient chunk per request constraints via previous API deductions)
                for i in range(0, remaining, 8):
                    batch_size = min(8, remaining - i)
                    batch = supported_failures[i:i + batch_size]
                    batch_str = ",".join(batch)
                    
                    tasks.append(worker_twelvedata(retry_session, scorer, batch_str, interval, latest_ts=None))
                await asyncio.gather(*tasks)
        else:
            print(f"\n[Phase 4] Skipped TwelveData fallback (no supported symbols internally mapped out of failed pool).")
            
    print("\n--- Pipeline Provider Scores ---")
    score_p = scorer.get_score("polygon")
    score_t = scorer.get_score("twelvedata")
    score_b = scorer.get_score("binance")
    
    print(f"Polygon Score: {score_p * 100:.1f}%")
    print(f"TwelveData Score: {score_t * 100:.1f}%")
    print(f"Binance Score: {score_b * 100:.1f}%")
    
    # SYSTEM-LEVEL ALERT LOGIC
    # Polygon and TwelveData form a united fallback pool. A system failure only occurs if BOTH fail.
    # Binance stands isolated, so a Binance failure triggers natively.
    if score_b < 0.80 or (score_p < 0.80 and score_t < 0.80):
        print("\n[ALERT] System-wide coverage dropped below safe thresholds! Review APIs/RateLimits.")
    
    end_time = time.time()
    runtime = end_time - start_time
    print(f"\n[GUARDRAIL SNAPSHOT] Total Runtime: {runtime:.2f}s | P: {score_p:.2f}, T: {score_t:.2f}, B: {score_b:.2f}")
    print(f"=== Advanced Async Pipeline Completed Successfully ===")

if __name__ == "__main__":
    asyncio.run(main_async())
