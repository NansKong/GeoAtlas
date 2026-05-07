import pandas as pd
import requests
import json
import os
from time import sleep

CACHE_FILE = "sp500_cache.json"


def get_top_stocks():
    """Manually curated high-liquidity stock universe divided between Finnhub and Polygon to manage rate limits"""
    print("Loading Top High-Liquidity Stocks...")
    
    # Polygon is strictly limited to 5 calls/min (EOD free tier)
    # We assign 10 highly critical stocks to Polygon. Will take ~2 mins to scrape.
    polygon_stocks = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META",
        "NVDA", "TSLA", "BRK.B", "JPM", "V"
    ]
    
    # TwelveData handles the rest, has better free tier EOD candle OHLC scaling.
    twelvedata_stocks = [
        "JNJ", "WMT", "PG", "MA", "HD",
        "DIS", "NFLX", "ADBE", "CRM", "INTC",
        "AMD", "COST", "PEP", "KO", "BAC",
        "CSCO", "MCD", "ABT", "TMO", "PFE"
    ]
    
    universe = []
    for s in polygon_stocks:
        universe.append({"symbol": s, "asset_type": "stocks", "source": "polygon"})
    for s in twelvedata_stocks:
        universe.append({"symbol": s, "asset_type": "stocks", "source": "twelvedata"})
        
    return universe

def get_top_crypto_symbols():
    """Top 50 crypto symbols for Binance"""
    print("Loading Top 50 Crypto symbols...")

    top_cryptos = [
        "BTC", "ETH", "BNB", "SOL", "USDC", "XRP", "ADA", "DOGE", "AVAX",
        "SHIB", "DOT", "LINK", "TRX", "MATIC", "BCH", "ICP", "NEAR", "UNI", "LTC",
        "APT", "ATOM", "ETC", "STX", "FIL", "OP", "XLM", "IMX", "RNDR",
        "INJ", "HBAR", "VET", "TAO", "MKR", "GRT", "LDO", "AR", "THETA", "KAS",
        "AAVE", "MNT", "FTM", "ALGO", "QNT", "BSV", "TIA", "SEI", "SNX", "GALA"
    ]

    return [
        {"symbol": f"{c}USDT", "asset_type": "crypto", "source": "binance"}
        for c in top_cryptos
    ]


def get_full_universe():
    # Phase 1: Crypto (Binance), Phase 2: Stocks (Polygon core), Phase 3: Stocks (TwelveData fallback)
    return get_top_crypto_symbols() + get_top_stocks()


if __name__ == "__main__":
    universe = get_full_universe()
    print(f"\nTotal symbols found: {len(universe)}")
    print(universe[:5])