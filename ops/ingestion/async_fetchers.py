import asyncio
import aiohttp
import os
from datetime import datetime, timezone
import pandas as pd
from rate_limiter import polygon_limiter, twelvedata_limiter, binance_limiter
from adapters import adapter

async def fetch_binance_async(client, scorer, symbol, period="2 years ago UTC", interval="1d"):
    """Fetch cryptocurrency data asynchronously via Python-Binance library"""
    import binance.exceptions
    
    await binance_limiter.consume(1)
    
    try:
        binance_interval = client.KLINE_INTERVAL_1DAY if interval == "1d" else client.KLINE_INTERVAL_1HOUR
        klines = await client.get_historical_klines(symbol, binance_interval, period)
        
        if not klines:
            print(f"[INFO] No data for {symbol} on Binance (valid empty response)")
            scorer.record_success("binance")
            return []
            
        all_data = []
        for k in klines[-2000:]: # Max safety cap
            ts = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
            all_data.append({
                'symbol': symbol,
                'timestamp': ts,
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'provider': "binance"
            })
            
        scorer.record_success("binance")
        binance_limiter.reward_rate()
        return all_data
        
    except binance.exceptions.BinanceAPIException as e:
        if e.status_code == 429:
            binance_limiter.penalize_rate()
        print(f"[Async] Binance API Error {symbol}: {e}")
        scorer.record_fail("binance", weight=1.0)
        return None
    except Exception as e:
        print(f"[Async] Binance fetch failed for {symbol}: {e}")
        scorer.record_fail("binance", weight=1.5)
        return None
async def fetch_polygon_async(session: aiohttp.ClientSession, scorer, symbol: str, period_days=730, interval="1d", latest_ts=None):
    """Fetch core stocks asynchronously from Polygon via aiohttp"""
    
    end_date = datetime.now(timezone.utc)
    if latest_ts and interval == "1d":
        # Incremental logic: if latest_ts is literally today, we DO NOT skip. 
        # We re-fetch from latest_ts to ensure the daily candle updates incrementally until market close!
        if latest_ts.date() > end_date.date():
            # Only skip if we somehow strictly have future data (prevent partial candle corruption)
            print(f"[Skipping] {symbol} already up-to-date for Polygon (latest: {latest_ts.date()})")
            return []
        # Fall-back re-overlap ensures weekends and missing partials naturally resolve.
        start_date = latest_ts
    else:
        start_date = end_date - pd.Timedelta(days=period_days)

    # Await natural token allowance dynamically without drifting execution threads
    await polygon_limiter.consume(1)
    
    api_key = os.getenv("POLYGON_API_KEY")
    timespan = "day" if interval == "1d" else "hour"
    
    # Normalize symbol: Polygon expects dashes not dots (e.g. BRK.B → BRK-B)
    symbol = adapter.get_symbol("polygon", symbol)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/{timespan}/{start_str}/{end_str}"
    params = {'adjusted': 'true', 'sort': 'asc', 'apiKey': api_key}
    
    all_data = []
    
    try:
        while url:
            async with session.get(url, params=params, timeout=15) as resp:
                print(f"[DEBUG] Polygon {symbol} → {resp.status}")
                
                if resp.status == 429:
                    polygon_limiter.penalize_rate()
                    print(f"[Async] Polygon 429 Rate Limit directly intercepted for {symbol}.")
                    scorer.record_fail("polygon", weight=0.3)
                    return None
                elif resp.status >= 500:
                    print(f"[Async] Polygon 500+ Error directly intercepted for {symbol}.")
                    scorer.record_fail("polygon", weight=1.5)
                    return None
                    
                resp.raise_for_status()
                polygon_limiter.reward_rate()
                data = await resp.json()
                
                if "results" in data and data["results"]:
                    for r in data["results"]:
                        ts = datetime.fromtimestamp(r["t"] / 1000.0, tz=timezone.utc)
                        all_data.append({
                            'symbol': symbol,
                            'timestamp': ts,
                            'open': float(r['o']),
                            'high': float(r['h']),
                            'low': float(r['l']),
                            'close': float(r['c']),
                            'volume': float(r['v']),
                            'provider': "polygon"
                        })
                
                # Check for pagination next_url
                next_url = data.get("next_url")
                if next_url:
                    url = next_url
                    params = {'apiKey': api_key}  # next_url already includes base params
                    await polygon_limiter.consume(1)  # paginated requests still cost limits
                else:
                    break
                    
        if not all_data:
            print(f"[INFO] No data for {symbol} (valid empty response)")
            
        scorer.record_success("polygon")
        return all_data
                
    except Exception as e:
        print(f"[Async] Polygon request failed ({symbol}): {e}")
        scorer.record_fail("polygon", weight=1.0)
        return None

async def fetch_twelvedata_async(session: aiohttp.ClientSession, scorer, symbol: str, interval="1day", latest_ts=None):
    """Fetch fallback stocks asynchronously from TwelveData via aiohttp"""
    
    if latest_ts and interval == "1d":
        if latest_ts.date() > datetime.now(timezone.utc).date():
            # Allow fetching same-day overlaps to prevent partial candle corruption (updates partials properly via SQL ON CONFLICT)
            print(f"[Skipping] {symbol} already up-to-date for TwelveData")
            return []

    mapped_interval = adapter.get_interval("twelvedata", interval)
    
    processed_symbols = [adapter.get_symbol("twelvedata", s) for s in symbol.split(",")]
    symbol_str = ",".join(processed_symbols)
    
    # 1. Smart Fallback Throttle + 2. Credit-aware limiter: each symbol mapped requires 1 API credit
    batch_size = len(processed_symbols)
    if twelvedata_limiter.tokens < batch_size:
        print(f"[SKIP] Not enough TwelveData credits to fallback {batch_size} symbols. Remaining: {twelvedata_limiter.tokens:.1f}")
        scorer.record_skip("twelvedata")
        return None
        
    await twelvedata_limiter.consume(batch_size)
    
    api_key = os.getenv("TWELVEDATA_API_KEY")
    url = "https://api.twelvedata.com/time_series"
    
    # Decrease row fetching drastically if we only need a few latest candles
    if latest_ts and interval == "1d":
        missing_days = max(1, (datetime.now(timezone.utc).date() - latest_ts.date()).days)
        outputsize = min(5000, missing_days + 5) # +5 buffer for safety/timezone drift
    else:
        outputsize = 5000
    
    params = {
        "symbol": symbol_str,
        "interval": mapped_interval,
        "outputsize": outputsize,
        "apikey": api_key
    }
    
    try:
        async with session.get(url, params=params, timeout=12) as resp:
            print(f"[DEBUG] TwelveData {symbol} → {resp.status}")
            
            if resp.status == 429:
                twelvedata_limiter.penalize_rate()
                print(f"[Async] TwelveData 429 on {symbol}. Backing off for 60s...")
                scorer.record_fail("twelvedata", weight=0.3)
                await asyncio.sleep(60) # 4. Backoff on 429
                return None
            elif resp.status >= 500:
                print(f"[Async] TwelveData 500+ on {symbol}.")
                scorer.record_fail("twelvedata", weight=1.5)
                return None
                
            resp.raise_for_status()
            twelvedata_limiter.reward_rate()
            data = await resp.json()
            
            # Safe Parsing: Validate dict response payload
            if not isinstance(data, dict):
                print(f"[TwelveData] Invalid response format for {symbol}: {data}")
                scorer.record_fail("twelvedata", weight=1.0)
                return None
                
            all_data = []
            
            def extract_values(sym_name, subdata):
                if "values" not in subdata: return
                for row in subdata["values"]:
                    try:
                        ts = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    except:
                        ts = datetime.strptime(row["datetime"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    all_data.append({
                        'symbol': sym_name,
                        'timestamp': ts,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']),
                        'provider': "twelvedata"
                    })

            if "," in symbol_str:
                for sym, subdata in data.items():
                    if isinstance(subdata, dict) and subdata.get("status") == "error":
                        print(f"[DEBUG DATA] TwelveData Error for {sym}: {subdata}")
                    else:
                        extract_values(sym, subdata)
            else:
                if data.get("status") == "error":
                    print(f"[DEBUG DATA] TwelveData Error: {data}")
                    scorer.record_fail("twelvedata", weight=1.0)
                    return None
                extract_values(symbol_str, data)
                
            scorer.record_success("twelvedata")
            return all_data
    except Exception as e:
        print(f"[Async] TwelveData fetch failed ({symbol}): {e}")
        scorer.record_fail("twelvedata", weight=1.0)
        return None
