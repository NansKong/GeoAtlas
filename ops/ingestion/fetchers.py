import yfinance as yf
import pandas as pd
from datetime import datetime
import time

# YFinance logic removed and replaced with Finnhub
def fetch_binance_bulk(symbols, period="2 years ago UTC", interval="1d"):
    from binance.client import Client
    import os
    import json
    
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    client = Client(api_key, api_secret)
    
    binance_interval = Client.KLINE_INTERVAL_1DAY if interval == "1d" else Client.KLINE_INTERVAL_1HOUR
    failed_symbols = []
    
    print(f"Fetching {interval} data for {len(symbols)} symbols from Binance...")
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] Fetching Binance data for {sym}...")
        all_data = [] # Reset per symbol chunk
        try:
            klines = client.get_historical_klines(sym, binance_interval, period)
            if not klines:
                failed_symbols.append(sym)
                continue
                
            for k in klines:
                ts = datetime.fromtimestamp(k[0] / 1000.0)
                all_data.append({
                    'symbol': sym,
                    'timestamp': ts,
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),
                    'provider': "binance"
                })
            
            # Yield the symbol's data so the pipeline can store it immediately
            yield all_data

        except Exception as e:
            print(f"Failed to fetch {sym} from Binance: {e}")
            failed_symbols.append(sym)
        # 5 calls per second is perfectly safe for binance historical
        time.sleep(0.2)        
    if failed_symbols:
        with open("failed_binance.json", "w") as f:
            json.dump(failed_symbols, f)
        print(f"Saved {len(failed_symbols)} failed Binance symbols to failed_binance.json")

def fetch_twelvedata_bulk(symbols, interval="1day"):
    import os
    import requests
    import time
    from datetime import datetime
    import json

    api_key = os.environ.get("TWELVEDATA_API_KEY")
    if not api_key:
        print("[WARNING] TWELVEDATA_API_KEY missing")
        return

    failed_symbols = []

    print(f"Fetching {interval} data for {len(symbols)} symbols from Twelve Data...")

    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] Fetching TwelveData for {sym}...")
        all_data = []

        try:
            url = "https://api.twelvedata.com/time_series"
            params = {
                "symbol": sym,
                "interval": interval,
                "outputsize": 5000,
                "apikey": api_key
            }

            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if "values" in data:
                for row in data["values"]:
                    ts = datetime.strptime(row["datetime"], "%Y-%m-%d")
                    all_data.append({
                        'symbol': sym,
                        'timestamp': ts,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']),
                        'provider': "twelvedata"
                    })

                yield all_data
            else:
                failed_symbols.append(sym)

        except Exception as e:
            print(f"TwelveData failed for {sym}: {e}")
            failed_symbols.append(sym)

        time.sleep(8)  # stay safe with rate limits

    if failed_symbols:
        with open("failed_twelvedata.json", "w") as f:
            json.dump(failed_symbols, f)

def format_candle(symbol, timestamp, row, provider):
    return {
        'symbol': symbol,
        'timestamp': timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp,
        'open': float(row['Open']) if not pd.isna(row['Open']) else None,
        'high': float(row['High']) if not pd.isna(row['High']) else None,
        'low': float(row['Low']) if not pd.isna(row['Low']) else None,
        'close': float(row['Close']) if not pd.isna(row['Close']) else None,
        'volume': float(row['Volume']) if not pd.isna(row['Volume']) else 0.0,
        'provider': provider
    }

def fetch_polygon_bulk(symbols, period_days=730, interval="1d"):
    """
    Fetch stock data from Polygon.io reliably.
    STRICT Rate Limit: 5 calls per minute (Free Tier) -> Requires 12+ second sleep between calls.
    """
    import os
    import requests
    import json
    
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        print("[WARNING] POLYGON_API_KEY not found in .env, skipping Polygon stocks.")
        return
        
    timespan = "day" if interval == "1d" else "hour"
    
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=period_days)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    failed_symbols = []
    
    print(f"Fetching {interval} data for {len(symbols)} symbols from Polygon (Strict 5 calls/min limit)...")
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] Fetching Polygon data for {sym}...")
        all_data = []
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/{timespan}/{start_str}/{end_str}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'apiKey': api_key
            }
            
            retry_count = 0
            max_retries = 3
            data = None
            
            while retry_count < max_retries:
                resp = requests.get(url, params=params, timeout=15)
                
                if resp.status_code == 429:
                    wait = 60 + (retry_count * 30)
                    print(f"Rate limited by Polygon! Sleeping {wait}s and retrying...")
                    time.sleep(wait)
                    retry_count += 1
                    continue
                
                resp.raise_for_status()
                data = resp.json()
                break # Success, break out of retry loop
                
            if retry_count == max_retries:
                print(f"Failed after retries: {sym}")
                failed_symbols.append(sym)
                continue

            if data and data.get("status") == "OK" and data.get("results"):
                for r in data["results"]:
                    # Polygon timestamps are in milliseconds
                    ts = datetime.fromtimestamp(r["t"] / 1000.0)
                    all_data.append({
                        'symbol': sym,
                        'timestamp': ts,
                        'open': float(r['o']),
                        'high': float(r['h']),
                        'low': float(r['l']),
                        'close': float(r['c']),
                        'volume': float(r['v']),
                        'provider': "polygon"
                    })
                
                yield all_data
            else:
                failed_symbols.append(sym)

        except Exception as e:
            print(f"Failed to fetch {sym} from Polygon: {e}")
            failed_symbols.append(sym)
        
        # 60 seconds / 5 calls = 12 seconds + 2s buffer margin = 14s
        if i < len(symbols) - 1:
            print("Sleeping 14 seconds to strictly respect Polygon API rate limits...")
            time.sleep(14)

    if failed_symbols:
        with open("failed_polygon.json", "w") as f:
            json.dump(failed_symbols, f)
        print(f"Saved {len(failed_symbols)} failed Polygon symbols to failed_polygon.json")
