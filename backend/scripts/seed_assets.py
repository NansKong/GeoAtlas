"""
Seed a comprehensive tradable asset universe for GeoAtlas.

Usage:
    python scripts/seed_assets.py
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from core.database import AsyncSessionFactory
from modules.market.models import Asset, AssetType, MarketPrice



# Curated reference prices used ONLY to seed a starting point for assets that
# have never had a real quote. Deliberately small and deliberately NOT a
# catch-all: an asset with no entry here gets no seeded price at all (see
# `_baseline_price`) rather than an invented number that would sit in the DB
# looking exactly like real, permanently-stale data.
INITIAL_PRICES = {
    "GLD": 402.75,
    "SLV": 59.07,
    "USO": 141.15,
    "UNG": 10.75,
    "PDBC": 19.06,
    "CPER": 39.53,
    "NVDA": 128.50,
    "AAPL": 224.30,
    "MSFT": 448.20,
    "AMZN": 254.98,
    "TSLA": 210.40,
    "GOOGL": 178.60,
    "META": 512.30,
    "PLTR": 34.20,
    "BTC": 64200.00,
    "ETH": 3450.00,
    "SOL": 145.20,
}


def _baseline_price(ticker: str) -> Optional[float]:
    """A known reference price to seed, or None if we don't have one.

    NEVER invents a placeholder (e.g. 100.0) for an unknown ticker — an
    unpriced asset should get its first quote from a live provider on the
    next snapshot cycle, not a synthetic guess that then looks identical to
    real data and, if that ticker's live providers are unavailable, never
    gets corrected.
    """
    return INITIAL_PRICES.get(ticker)


SEED_ASSETS = [
    # ── US MEGA-CAP TECH ─────────────────────────────────────────────────────
    {"ticker": "AAPL",  "name": "Apple Inc",                    "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Consumer Electronics",   "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "MSFT",  "name": "Microsoft Corp",               "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Software",               "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "GOOGL", "name": "Alphabet Inc",                 "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Internet Services",       "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "AMZN",  "name": "Amazon.com Inc",               "asset_type": AssetType.STOCK, "sector": "Consumer Cyclical","industry": "E-Commerce",            "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "META",  "name": "Meta Platforms Inc",           "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Social Media",           "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "NVDA",  "name": "NVIDIA Corp",                  "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "AMD",   "name": "Advanced Micro Devices",       "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "TSLA",  "name": "Tesla Inc",                    "asset_type": AssetType.STOCK, "sector": "Consumer Cyclical","industry": "Electric Vehicles",     "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "TSM",   "name": "Taiwan Semiconductor",         "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "Taiwan",        "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "AVGO",  "name": "Broadcom Inc",                 "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "INTC",  "name": "Intel Corp",                   "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "QCOM",  "name": "Qualcomm Inc",                 "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductors",         "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "ORCL",  "name": "Oracle Corp",                  "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Enterprise Software",    "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "CRM",   "name": "Salesforce Inc",               "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "SaaS",                   "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "IBM",   "name": "IBM Corp",                     "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "IT Services",            "country": "United States", "exchange": "NYSE",     "currency": "USD"},

    # ── FINANCIALS ────────────────────────────────────────────────────────────
    {"ticker": "JPM",   "name": "JPMorgan Chase",               "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Banking",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "BAC",   "name": "Bank of America",              "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Banking",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "GS",    "name": "Goldman Sachs",                "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Investment Banking",     "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "MS",    "name": "Morgan Stanley",               "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Investment Banking",     "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "C",     "name": "Citigroup Inc",                "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Banking",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "WFC",   "name": "Wells Fargo",                  "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Banking",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "BLK",   "name": "BlackRock Inc",                "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Asset Management",       "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "V",     "name": "Visa Inc",                     "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Payments",               "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "MA",    "name": "Mastercard Inc",               "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Payments",               "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "PYPL",  "name": "PayPal Holdings",              "asset_type": AssetType.STOCK, "sector": "Financials",      "industry": "Fintech",                "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},

    # ── ENERGY ───────────────────────────────────────────────────────────────
    {"ticker": "XOM",   "name": "Exxon Mobil Corp",             "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oil & Gas",              "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "CVX",   "name": "Chevron Corp",                 "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oil & Gas",              "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "COP",   "name": "ConocoPhillips",               "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oil & Gas",              "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "BP",    "name": "BP plc",                       "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oil & Gas",              "country": "United Kingdom","exchange": "NYSE",     "currency": "USD"},
    {"ticker": "SHEL",  "name": "Shell plc",                    "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oil & Gas",              "country": "United Kingdom","exchange": "NYSE",     "currency": "USD"},
    {"ticker": "SLB",   "name": "SLB (Schlumberger)",           "asset_type": AssetType.STOCK, "sector": "Energy",          "industry": "Oilfield Services",      "country": "United States", "exchange": "NYSE",     "currency": "USD"},

    # ── HEALTHCARE ────────────────────────────────────────────────────────────
    {"ticker": "JNJ",   "name": "Johnson & Johnson",            "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Pharmaceuticals",        "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "PFE",   "name": "Pfizer Inc",                   "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Pharmaceuticals",        "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "ABBV",  "name": "AbbVie Inc",                   "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Biopharmaceuticals",     "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "MRK",   "name": "Merck & Co",                   "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Pharmaceuticals",        "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "LLY",   "name": "Eli Lilly & Co",               "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Pharmaceuticals",        "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "UNH",   "name": "UnitedHealth Group",           "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Health Insurance",       "country": "United States", "exchange": "NYSE",     "currency": "USD"},

    # ── CONSUMER / RETAIL ────────────────────────────────────────────────────
    {"ticker": "WMT",   "name": "Walmart Inc",                  "asset_type": AssetType.STOCK, "sector": "Consumer Staples","industry": "Retail",                 "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "KO",    "name": "Coca-Cola Co",                 "asset_type": AssetType.STOCK, "sector": "Consumer Staples","industry": "Beverages",              "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "PEP",   "name": "PepsiCo Inc",                  "asset_type": AssetType.STOCK, "sector": "Consumer Staples","industry": "Beverages",              "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "MCD",   "name": "McDonald's Corp",              "asset_type": AssetType.STOCK, "sector": "Consumer Cyclical","industry": "Restaurants",           "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "NKE",   "name": "Nike Inc",                     "asset_type": AssetType.STOCK, "sector": "Consumer Cyclical","industry": "Footwear & Apparel",    "country": "United States", "exchange": "NYSE",     "currency": "USD"},

    # ── INDUSTRIALS / DEFENSE ────────────────────────────────────────────────
    {"ticker": "BA",    "name": "Boeing Co",                    "asset_type": AssetType.STOCK, "sector": "Industrials",     "industry": "Aerospace & Defense",    "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "LMT",   "name": "Lockheed Martin",              "asset_type": AssetType.STOCK, "sector": "Industrials",     "industry": "Defense",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "RTX",   "name": "RTX Corp (Raytheon)",          "asset_type": AssetType.STOCK, "sector": "Industrials",     "industry": "Defense",                "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "CAT",   "name": "Caterpillar Inc",              "asset_type": AssetType.STOCK, "sector": "Industrials",     "industry": "Heavy Machinery",        "country": "United States", "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "GE",    "name": "GE Aerospace",                 "asset_type": AssetType.STOCK, "sector": "Industrials",     "industry": "Aerospace & Defense",    "country": "United States", "exchange": "NYSE",     "currency": "USD"},

    # ── GLOBAL EQUITIES ──────────────────────────────────────────────────────
    {"ticker": "BABA",  "name": "Alibaba Group",                "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "E-Commerce",             "country": "China",         "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "BIDU",  "name": "Baidu Inc",                    "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Internet Services",       "country": "China",         "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "NVO",   "name": "Novo Nordisk",                 "asset_type": AssetType.STOCK, "sector": "Healthcare",      "industry": "Pharmaceuticals",        "country": "Denmark",       "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "ASML",  "name": "ASML Holding",                 "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Semiconductor Equipment","country": "Netherlands",   "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "SAP",   "name": "SAP SE",                       "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Enterprise Software",    "country": "Germany",       "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "TM",    "name": "Toyota Motor Corp",            "asset_type": AssetType.STOCK, "sector": "Consumer Cyclical","industry": "Automobiles",           "country": "Japan",         "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "SONY",  "name": "Sony Group Corp",              "asset_type": AssetType.STOCK, "sector": "Technology",      "industry": "Consumer Electronics",   "country": "Japan",         "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "RIO",   "name": "Rio Tinto",                    "asset_type": AssetType.STOCK, "sector": "Materials",       "industry": "Mining",                 "country": "Australia",     "exchange": "NYSE",     "currency": "USD"},
    {"ticker": "VALE",  "name": "Vale SA",                      "asset_type": AssetType.STOCK, "sector": "Materials",       "industry": "Mining",                 "country": "Brazil",        "exchange": "NYSE",     "currency": "USD"},

    # ── BROAD MARKET ETFs ────────────────────────────────────────────────────
    {"ticker": "SPY",   "name": "SPDR S&P 500 ETF",            "asset_type": AssetType.ETF,   "sector": "Broad Market",    "industry": "Index ETF",              "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "QQQ",   "name": "Invesco QQQ Trust",           "asset_type": AssetType.ETF,   "sector": "Technology",      "industry": "Index ETF",              "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "IWM",   "name": "iShares Russell 2000 ETF",    "asset_type": AssetType.ETF,   "sector": "Broad Market",    "industry": "Index ETF",              "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "DIA",   "name": "SPDR Dow Jones ETF",          "asset_type": AssetType.ETF,   "sector": "Broad Market",    "industry": "Index ETF",              "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "VTI",   "name": "Vanguard Total Market ETF",   "asset_type": AssetType.ETF,   "sector": "Broad Market",    "industry": "Index ETF",              "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "EFA",   "name": "iShares MSCI EAFE ETF",       "asset_type": AssetType.ETF,   "sector": "International",   "industry": "Index ETF",              "country": "Global",        "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "EEM",   "name": "iShares MSCI Emerging ETF",   "asset_type": AssetType.ETF,   "sector": "Emerging Markets","industry": "Index ETF",              "country": "Global",        "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "VWO",   "name": "Vanguard Emerging Markets ETF","asset_type": AssetType.ETF,  "sector": "Emerging Markets","industry": "Index ETF",              "country": "Global",        "exchange": "NYSEARCA", "currency": "USD"},

    # ── SECTOR ETFs ──────────────────────────────────────────────────────────
    {"ticker": "XLE",   "name": "Energy Select SPDR ETF",      "asset_type": AssetType.ETF,   "sector": "Energy",          "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLF",   "name": "Financial Select SPDR ETF",   "asset_type": AssetType.ETF,   "sector": "Financials",      "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLK",   "name": "Technology Select SPDR ETF",  "asset_type": AssetType.ETF,   "sector": "Technology",      "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLV",   "name": "Health Care Select SPDR ETF", "asset_type": AssetType.ETF,   "sector": "Healthcare",      "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLI",   "name": "Industrial Select SPDR ETF",  "asset_type": AssetType.ETF,   "sector": "Industrials",     "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLB",   "name": "Materials Select SPDR ETF",   "asset_type": AssetType.ETF,   "sector": "Materials",       "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "XLU",   "name": "Utilities Select SPDR ETF",   "asset_type": AssetType.ETF,   "sector": "Utilities",       "industry": "Sector ETF",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},

    # ── COMMODITY ETFs & METALS ─────────────────────────────────────────────
    {"ticker": "GLD",   "name": "SPDR Gold Shares",            "asset_type": AssetType.COMMODITY, "sector": "Metals",          "industry": "Precious Metals",       "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "SLV",   "name": "iShares Silver Trust",        "asset_type": AssetType.COMMODITY, "sector": "Metals",          "industry": "Precious Metals",       "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "USO",   "name": "United States Oil Fund",      "asset_type": AssetType.COMMODITY, "sector": "Energy",          "industry": "Crude Oil",             "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "UNG",   "name": "United States Natural Gas Fund","asset_type": AssetType.COMMODITY, "sector": "Energy",        "industry": "Natural Gas",           "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "PDBC",  "name": "Invesco Commodity ETF",       "asset_type": AssetType.COMMODITY, "sector": "Commodities",     "industry": "Broad Commodities",     "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "CPER",  "name": "United States Copper Index",  "asset_type": AssetType.COMMODITY, "sector": "Metals",          "industry": "Base Metals",           "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},

    # ── BOND / RATE ETFs ─────────────────────────────────────────────────────
    {"ticker": "TLT",   "name": "iShares 20+ Year Treasury ETF","asset_type": AssetType.ETF,  "sector": "Fixed Income",    "industry": "Government Bond ETF",    "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "IEF",   "name": "iShares 7-10 Year Treasury ETF","asset_type": AssetType.ETF, "sector": "Fixed Income",    "industry": "Government Bond ETF",    "country": "United States", "exchange": "NASDAQ",   "currency": "USD"},
    {"ticker": "HYG",   "name": "iShares High Yield Bond ETF", "asset_type": AssetType.ETF,   "sector": "Fixed Income",    "industry": "Corporate Bond ETF",     "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "LQD",   "name": "iShares Investment Grade Bond ETF","asset_type": AssetType.ETF,"sector": "Fixed Income",  "industry": "Corporate Bond ETF",     "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},

    # ── VOLATILITY ───────────────────────────────────────────────────────────
    {"ticker": "UVXY",  "name": "ProShares Ultra VIX ETF",     "asset_type": AssetType.ETF,   "sector": "Volatility",      "industry": "Volatility ETF",         "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},

    # ── FOREX PAIRS ──────────────────────────────────────────────────────────
    {"ticker": "EURUSD","name": "Euro / US Dollar",            "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "USD"},
    {"ticker": "GBPUSD","name": "British Pound / US Dollar",   "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "USD"},
    {"ticker": "USDJPY","name": "US Dollar / Japanese Yen",    "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "JPY"},
    {"ticker": "USDCNH","name": "US Dollar / Chinese Yuan",    "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "CNH"},
    {"ticker": "AUDUSD","name": "Australian Dollar / USD",     "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "USD"},
    {"ticker": "USDCAD","name": "US Dollar / Canadian Dollar", "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Major Pair",             "country": "Global",        "exchange": "OTC",      "currency": "CAD"},
    {"ticker": "USDCHF","name": "US Dollar / Swiss Franc",     "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "Safe Haven",             "country": "Global",        "exchange": "OTC",      "currency": "CHF"},
    {"ticker": "USDINR","name": "US Dollar / Indian Rupee",    "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "EM Pair",                "country": "Global",        "exchange": "OTC",      "currency": "INR"},
    {"ticker": "USDRUB","name": "US Dollar / Russian Ruble",   "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "EM Pair",                "country": "Global",        "exchange": "OTC",      "currency": "RUB"},
    {"ticker": "USDBRL","name": "US Dollar / Brazilian Real",  "asset_type": AssetType.FOREX,  "sector": "FX",              "industry": "EM Pair",                "country": "Global",        "exchange": "OTC",      "currency": "BRL"},

    # ── CRYPTO ───────────────────────────────────────────────────────────────
    {"ticker": "BTC",   "name": "Bitcoin",                      "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 1",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "ETH",   "name": "Ethereum",                     "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 1",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "SOL",   "name": "Solana",                       "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 1",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "BNB",   "name": "Binance Coin",                 "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Exchange Token",         "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "XRP",   "name": "XRP (Ripple)",                 "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Payments",              "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "ADA",   "name": "Cardano",                      "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 1",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "AVAX",  "name": "Avalanche",                    "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 1",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "DOGE",  "name": "Dogecoin",                     "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Meme Coin",             "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "DOT",   "name": "Polkadot",                     "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Layer 0",               "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
    {"ticker": "LINK",  "name": "Chainlink",                    "asset_type": AssetType.CRYPTO, "sector": "Crypto",          "industry": "Oracle",                "country": "Global",        "exchange": "CRYPTO",   "currency": "USD"},
]


async def async_main() -> None:
    created = 0
    updated = 0

    async with AsyncSessionFactory() as session:
        for data in SEED_ASSETS:
            res = await session.execute(
                select(Asset).where(Asset.ticker == data["ticker"])
            )
            existing = res.scalar_one_or_none()

            if existing:
                existing.name       = data["name"]
                existing.asset_type = data["asset_type"]
                existing.sector     = data["sector"]
                existing.industry   = data["industry"]
                existing.country    = data["country"]
                existing.exchange   = data["exchange"]
                existing.currency   = data["currency"]
                updated += 1
            else:
                session.add(Asset(**data))
                created += 1

        await session.commit()

        # Seed baseline quotes if missing
        seeded_quotes = 0
        skipped_unpriced = 0
        all_assets_res = await session.execute(select(Asset))
        all_assets = all_assets_res.scalars().all()
        now = datetime.now(timezone.utc)

        for asset in all_assets:
            existing_q_res = await session.execute(
                select(MarketPrice).where(MarketPrice.asset_id == asset.id).limit(1)
            )
            existing_q = existing_q_res.first()
            if not existing_q:
                price = _baseline_price(asset.ticker)
                if price is None:
                    # No curated reference price — leave it unseeded so the live
                    # snapshot pipeline populates the first REAL quote instead of
                    # a synthetic placeholder.
                    skipped_unpriced += 1
                    continue
                session.add(
                    MarketPrice(
                        asset_id=asset.id,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=1000.0,
                        timestamp=now,
                    )
                )
                seeded_quotes += 1

        await session.commit()

    total = len(SEED_ASSETS)
    print(
        f"Asset seed complete: created={created}, updated={updated}, "
        f"seeded_quotes={seeded_quotes}, skipped_unpriced={skipped_unpriced}, total={total}"
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

