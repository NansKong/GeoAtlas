from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException, WebSocket
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionFactory
from core.http import global_http_client, PROVIDERS, RequestCoalescer, LRUCache
from core.redis import redis_get, redis_set
from modules.market.models import Asset, AssetType, MarketPrice
from modules.market.schemas import FundamentalsOut, OHLCVOut, OHLCVPointOut, QuoteOut

REALTIME_PRICE_TTL_SECONDS = 15
DAILY_OHLCV_TTL_SECONDS = 3600
HISTORICAL_1Y_TTL_SECONDS = 86400
FUNDAMENTALS_TTL_SECONDS = 7 * 24 * 3600

logger = logging.getLogger(__name__)

# ─── Coalescer for quote de-duplication ──────────────────────────────────────
_quote_coalescer = RequestCoalescer(timeout=5.0)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _quote_cache_key(ticker: str) -> str:
    return f"market:quote:{ticker.upper()}"


def _ohlcv_cache_key(ticker: str, interval: str, limit: int) -> str:
    return f"market:ohlcv:{ticker.upper()}:{interval}:{limit}"


def _historical_1y_cache_key(ticker: str) -> str:
    return f"market:historical_1y:{ticker.upper()}"


def _fundamentals_cache_key(ticker: str) -> str:
    return f"market:fundamentals:{ticker.upper()}"


def _require_live_api() -> bool:
    return bool(settings.MARKET_REQUIRE_LIVE_API)


async def _cache_get_json(key: str) -> Optional[dict]:
    raw = await redis_get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _cache_set_json(key: str, payload: dict, ttl_seconds: int) -> None:
    await redis_set(key, json.dumps(payload), ttl_seconds=ttl_seconds)


NAME_ALIAS_MAP: dict[str, str] = {
    "AMAZON": "AMZN",
    "APPLE": "AAPL",
    "MICROSOFT": "MSFT",
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "SILVER": "SLV",
    "GOLD": "GLD",
    "OIL": "USO",
    "CRUDE OIL": "USO",
    "NATURAL GAS": "UNG",
    "GAS": "UNG",
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "SOLANA": "SOL",
    "DISNEY": "DIS",
    "NETFLIX": "NFLX",
    "PALANTIR": "PLTR",
    "AMD": "AMD",
    "COINBASE": "COIN",
    "META": "META",
    "FACEBOOK": "META",
}


def _escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input cannot widen the pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ─── Yahoo Finance symbol mapping ─────────────────────────────────────────────
# Yahoo scopes crypto/forex/futures symbols with a type suffix. A bare ticker
# passed through unmapped resolves to the WRONG instrument — "BTC" alone is
# Yahoo's Grayscale Bitcoin Trust ETF, not Bitcoin — so every ticker must go
# through this layer before it reaches a Yahoo endpoint. `_strip_yahoo_suffix`
# is the inverse, used when a Yahoo *search* hit becomes a new internal ticker.

COMMODITY_FUTURES_ROOTS = {"GC", "CL", "NG", "SI", "HG"}

YAHOO_QUOTE_TYPE_MAP: dict[str, AssetType] = {
    "EQUITY": AssetType.STOCK,
    "ETF": AssetType.ETF,
    "CRYPTOCURRENCY": AssetType.CRYPTO,
    "CURRENCY": AssetType.FOREX,
    "FUTURE": AssetType.COMMODITY,
    "INDEX": AssetType.INDEX,
}


def _yahoo_symbol(ticker: str, asset_type: AssetType) -> str:
    """Map an internal ticker to the symbol Yahoo Finance expects."""
    t = ticker.upper().replace("/", "")
    if asset_type == AssetType.CRYPTO:
        return t if t.endswith("-USD") else f"{t}-USD"
    if asset_type == AssetType.FOREX:
        return t if t.endswith("=X") else f"{t}=X"
    if asset_type == AssetType.COMMODITY:
        if t.endswith("=F") or t.endswith("=X"):
            return t
        if t in COMMODITY_FUTURES_ROOTS:
            return f"{t}=F"
        return t
    return t


def _strip_yahoo_suffix(symbol: str, asset_type: AssetType) -> str:
    """Inverse of `_yahoo_symbol`: turn a symbol Yahoo returned back into our
    internal bare-ticker convention (e.g. "BTC-USD" -> "BTC", "EURUSD=X" -> "EURUSD")."""
    s = symbol.upper()
    if asset_type == AssetType.CRYPTO and s.endswith("-USD"):
        return s[: -len("-USD")]
    if asset_type == AssetType.FOREX and s.endswith("=X"):
        return s[: -len("=X")]
    if asset_type == AssetType.COMMODITY and s.endswith("=F"):
        return s[: -len("=F")]
    return s


async def _yahoo_search(query: str) -> Optional[dict]:
    """Resolve free text (a company name, or an unfamiliar symbol) to a Yahoo
    Finance instrument. Free, no API key. Returns the top match's symbol/name/
    type/exchange, or None — Yahoo returns an empty list for garbage input
    rather than guessing, so a miss here is a real miss."""
    ctx = PROVIDERS["yahoo"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": 1, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response is None or response.status_code != 200:
            return None
        quotes = response.json().get("quotes") or []
        if not quotes:
            return None
        top = quotes[0]
        symbol = top.get("symbol")
        if not symbol:
            return None
        return {
            "symbol": symbol,
            "name": top.get("shortname") or top.get("longname"),
            "quote_type": (top.get("quoteType") or "").upper(),
            "exchange": top.get("exchange"),
        }
    except Exception as exc:
        logger.debug("Yahoo search failed for '%s': %s", query, exc)
        return None


async def _get_asset_or_404(db: AsyncSession, ticker: str) -> Asset:
    clean_query = ticker.strip()
    ticker_upper = clean_query.upper()

    # 0. Common name alias lookup (e.g. "amazon" -> "AMZN", "silver" -> "SLV")
    if ticker_upper in NAME_ALIAS_MAP:
        ticker_upper = NAME_ALIAS_MAP[ticker_upper]

    # 1a. Exact ticker match wins outright. A fuzzy name match must never shadow a
    #     real symbol: "%C%" matches "Apple Inc", "%V%" matches "NVIDIA Corp", etc.,
    #     so an OR-query would happily return the wrong company for Citigroup or Visa.
    result = await db.execute(select(Asset).where(Asset.ticker == ticker_upper))
    asset = result.scalars().first()
    if asset:
        return asset

    # 1b. Otherwise fall back to a company-name search. Require >= 3 characters so a
    #     short unknown ticker cannot match an unrelated name, escape LIKE wildcards
    #     from user input, and order deterministically (tightest name first).
    if len(clean_query) >= 3:
        name_pattern = "%" + _escape_like(clean_query) + "%"
        result = await db.execute(
            select(Asset)
            .where(Asset.name.ilike(name_pattern, escape="\\"))
            .order_by(func.length(Asset.name).asc(), Asset.ticker.asc())
            .limit(1)
        )
        asset = result.scalars().first()
        if asset:
            return asset

    # 2. Polygon Search Reference API if API key present
    if settings.POLYGON_API_KEY:
        try:
            ctx = PROVIDERS["polygon"]
            resp = await ctx.execute(
                global_http_client.get,
                "https://api.polygon.io/v3/reference/tickers",
                params={"search": clean_query, "active": "true", "limit": 1, "apiKey": settings.POLYGON_API_KEY},
            )
            if resp and resp.status_code == 200:
                results = resp.json().get("results", [])
                if results and results[0].get("ticker"):
                    found_ticker = results[0]["ticker"].upper()
                    result = await db.execute(select(Asset).where(Asset.ticker == found_ticker))
                    existing = result.scalar_one_or_none()
                    if existing:
                        return existing
                    ticker_upper = found_ticker
        except Exception as exc:
            logger.debug("Polygon search failed for '%s': %s", clean_query, exc)

    # Dynamic asset auto-discovery
    logger.info("Asset '%s' not in DB — initiating dynamic discovery...", ticker_upper)
    name = f"{ticker_upper}"
    asset_type = AssetType.STOCK
    sector = "General"
    industry = "Equities"
    exchange = "US"
    currency = "USD"
    country = "United States"

    # 1. Try fetching official ticker metadata from Polygon if API key available
    if settings.POLYGON_API_KEY:
        try:
            ctx = PROVIDERS["polygon"]
            resp = await ctx.execute(
                global_http_client.get,
                f"https://api.polygon.io/v3/reference/tickers/{ticker_upper}",
                params={"apiKey": settings.POLYGON_API_KEY},
            )
            if resp and resp.status_code == 200:
                pdata = resp.json().get("results", {})
                if pdata:
                    name = pdata.get("name") or name
                    market = (pdata.get("market") or "").lower()
                    type_str = (pdata.get("type") or "").upper()
                    if market == "crypto" or "CRYPTO" in type_str:
                        asset_type = AssetType.CRYPTO
                    elif market == "fx" or "FX" in type_str:
                        asset_type = AssetType.FOREX
                    elif "ETF" in type_str:
                        asset_type = AssetType.ETF
                    elif market == "indices" or "INDEX" in type_str:
                        asset_type = AssetType.INDEX
                    exchange = pdata.get("primary_exchange") or exchange
                    currency = (pdata.get("currency_name") or currency).upper()
                    locale = pdata.get("locale") or ""
                    country = "Global" if locale == "global" else "United States"
        except Exception as exc:
            logger.debug("Polygon ticker metadata lookup skipped for %s: %s", ticker_upper, exc)

    # 2. Yahoo Finance search — free, no API key. Gap-fills when Polygon has no
    #    key configured or found nothing, and classifies the instrument directly
    #    from Yahoo's quoteType instead of guessing from ticker shape like the
    #    pattern-matching fallback below.
    if name == ticker_upper:
        yahoo_hit = await _yahoo_search(clean_query)
        if yahoo_hit:
            hit_type = YAHOO_QUOTE_TYPE_MAP.get(yahoo_hit["quote_type"])
            if hit_type is not None:
                found_ticker = _strip_yahoo_suffix(yahoo_hit["symbol"], hit_type)
                result = await db.execute(select(Asset).where(Asset.ticker == found_ticker))
                existing = result.scalar_one_or_none()
                if existing:
                    return existing
                ticker_upper = found_ticker
                name = yahoo_hit.get("name") or name
                asset_type = hit_type
                exchange = yahoo_hit.get("exchange") or exchange
                if asset_type == AssetType.CRYPTO:
                    sector, industry, country = "Crypto", "Layer 1", "Global"
                elif asset_type == AssetType.COMMODITY:
                    sector, industry, country = "Commodities", "Futures", "Global"
                elif asset_type == AssetType.FOREX:
                    sector, industry, country = "FX", "Major Pair", "Global"

    # 3. Pattern-based fallback inference
    if name == ticker_upper:
        known_cryptos = {
            "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "DOT", "LINK",
            "AVAX", "MATIC", "SHIB", "LTC", "UNI", "PEPE", "NEAR", "APT", "SUI",
            "RENDER", "FET", "INJ", "TIA", "RUNE", "TAO", "WIF", "AR", "FLOKI"
        }
        if ticker_upper in known_cryptos or ticker_upper.endswith("USDT"):
            asset_type = AssetType.CRYPTO
            name = f"{ticker_upper} Crypto"
            exchange = "CRYPTO"
            sector = "Crypto"
            industry = "Layer 1"
            country = "Global"
        elif ticker_upper.endswith("=F") or ticker_upper in {"GC", "CL", "NG", "SI", "HG", "XAUUSD", "XAGUSD"}:
            asset_type = AssetType.COMMODITY
            name = f"{ticker_upper} Commodity"
            exchange = "NYMEX"
            sector = "Commodities"
            industry = "Futures"
            country = "Global"
        elif len(ticker_upper) == 6 and ticker_upper in {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "USDCNH", "USDINR"}:
            asset_type = AssetType.FOREX
            name = f"{ticker_upper[:3]}/{ticker_upper[3:]} Currency Pair"
            exchange = "OTC"
            sector = "FX"
            industry = "Major Pair"
            country = "Global"
        else:
            name = f"{ticker_upper} Inc"

    try:
        new_asset = Asset(
            ticker=ticker_upper,
            name=name,
            asset_type=asset_type,
            sector=sector,
            industry=industry,
            country=country,
            exchange=exchange,
            currency=currency,
        )
        db.add(new_asset)
        await db.commit()
        await db.refresh(new_asset)
        logger.info("Dynamically registered new asset in DB: %s (%s, %s)", ticker_upper, name, asset_type.value)
        return new_asset
    except Exception as exc:
        await db.rollback()
        logger.warning("Failed to auto-register asset %s: %s", ticker_upper, exc)
        # Final safety check if another worker registered it concurrently
        result = await db.execute(select(Asset).where(Asset.ticker == ticker_upper))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        raise HTTPException(status_code=404, detail=f"Asset '{ticker_upper}' could not be registered")


async def _quote_from_polygon(ticker: str) -> Optional[dict]:
    if not settings.POLYGON_API_KEY:
        return None
    ctx = PROVIDERS["polygon"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
            params={"adjusted": "true", "apiKey": settings.POLYGON_API_KEY},
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") or []
        if not rows:
            return None
        row = rows[0]
        as_of = datetime.fromtimestamp(row["t"] / 1000, tz=timezone.utc)
        return {"price": float(row["c"]), "as_of": as_of, "source": "polygon"}
    except Exception as exc:
        logger.warning("Polygon quote failed for %s: %s", ticker, exc)
        return None


async def _quote_from_finnhub(ticker: str) -> Optional[dict]:
    if not settings.FINNHUB_API_KEY:
        return None
    ctx = PROVIDERS["finnhub"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": settings.FINNHUB_API_KEY},
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        price = payload.get("c")
        timestamp = payload.get("t")
        if price is None or float(price) <= 0:
            return None
        as_of = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
        return {"price": float(price), "as_of": as_of, "source": "finnhub"}
    except Exception as exc:
        logger.warning("Finnhub quote failed for %s: %s", ticker, exc)
        return None


async def _quote_from_twelve_data(ticker: str, asset_type: AssetType) -> Optional[dict]:
    if not settings.TWELVEDATA_API_KEY:
        return None
    symbol = _normalize_twelve_symbol(ticker, asset_type)
    ctx = PROVIDERS["twelvedata"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.twelvedata.com/price",
            params={"symbol": symbol, "apikey": settings.TWELVEDATA_API_KEY},
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        price = payload.get("price")
        if price is None:
            return None
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "twelve_data",
        }
    except Exception as exc:
        logger.warning("TwelveData quote failed for %s (%s): %s", ticker, symbol, exc)
        return None
async def _quote_from_binance(ticker: str) -> Optional[dict]:
    # normalized to USDT for Binance
    symbol = ticker.replace("-", "").replace("/", "").upper()
    if symbol.endswith("USD"):
        symbol = symbol[:-3] + "USDT"
    ctx = PROVIDERS["binance"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        price = payload.get("price")
        if price is None:
            return None
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "binance",
        }
    except Exception as exc:
        logger.warning("Binance quote failed for %s (%s): %s", ticker, symbol, exc)
        return None

async def _quote_from_eodhd(ticker: str) -> Optional[dict]:
    if not getattr(settings, "EODHD_API_KEY", None):
        return None
    ctx = PROVIDERS["eodhd"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://eodhd.com/api/real-time/{ticker}.US",
            params={"api_token": settings.EODHD_API_KEY, "fmt": "json"},
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        # EODHD single ticker response
        price = payload.get("close")
        if price is None:
            return None
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "eodhd",
        }
    except Exception as exc:
        logger.warning("EODHD quote failed for %s: %s", ticker, exc)
        return None

async def _quote_from_fcsapi(ticker: str) -> Optional[dict]:
    if not getattr(settings, "FCS_API_KEY", None):
        return None
    symbol = _normalize_twelve_symbol(ticker, AssetType.FOREX) 
    ctx = PROVIDERS["fcs"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://fcsapi.com/api-v3/forex/latest",
            params={"symbol": symbol, "access_key": settings.FCS_API_KEY},
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        if not payload.get("status"):
            return None
        rows = payload.get("response", [])
        if not rows:
            return None
        row = rows[0]
        price = row.get("c")
        if price is None:
            return None
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "fcs",
        }
    except Exception as exc:
        logger.warning("FCS API quote failed for %s: %s", ticker, exc)
        return None

async def _quote_from_alpha_vantage(ticker: str) -> Optional[dict]:
    if not getattr(settings, "ALPHA_VANTAGE_API_KEY", None):
        return None
    ctx = PROVIDERS["alphavantage"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": settings.ALPHA_VANTAGE_API_KEY},
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        quote = payload.get("Global Quote", {})
        price = quote.get("05. price")
        if price is None:
            return None
        # Detect rate-limit note returned as 200 JSON (AV free tier)
        if "Note" in payload or "Information" in payload:
            logger.warning("AlphaVantage rate limit hit for %s", ticker)
            return None
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "alphavantage",
        }
    except Exception as exc:
        logger.warning("AlphaVantage quote failed for %s: %s", ticker, exc)
        return None


async def _quote_from_alpaca(ticker: str) -> Optional[dict]:
    """Alpaca Market Data API — free Basic plan gives IEX real-time quotes for US equities."""
    if not getattr(settings, "ALPACA_API_KEY_ID", None) or not getattr(settings, "ALPACA_API_SECRET_KEY", None):
        return None
    ctx = PROVIDERS["alpaca"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://data.alpaca.markets/v2/stocks/{ticker}/quotes/latest",
            headers={
                "APCA-API-KEY-ID": settings.ALPACA_API_KEY_ID,
                "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET_KEY,
            },
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        quote = payload.get("quote", {})
        # Use the mid of the ask/bid as a proxy for the latest trade price. Outside IEX
        # trading hours (and for symbols IEX does not quote) Alpaca returns ap/bp of 0
        # rather than null — treating those as a real price would publish and persist a
        # $0.00 quote, so only positive sides count.
        ask = _safe_float(quote.get("ap"))  # ask price
        bid = _safe_float(quote.get("bp"))  # bid price
        sides = [side for side in (ask, bid) if side is not None and side > 0]
        if not sides:
            return None
        price = sum(sides) / len(sides)
        return {
            "price": price,
            "as_of": datetime.now(timezone.utc),
            "source": "alpaca",
        }
    except Exception as exc:
        logger.warning("Alpaca quote failed for %s: %s", ticker, exc)
        return None


async def _quote_from_yahoo(ticker: str, asset_type: AssetType) -> Optional[dict]:
    """Yahoo Finance chart endpoint — free, no API key, covers all asset types in
    one call. Gap-fill + final fallback: tried only once every keyed provider
    above has failed or is unconfigured."""
    symbol = _yahoo_symbol(ticker, asset_type)
    ctx = PROVIDERS["yahoo"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "1d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response is None or response.status_code != 200:
            return None
        results = response.json().get("chart", {}).get("result") or []
        if not results:
            return None
        meta = results[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        as_of_ts = meta.get("regularMarketTime")
        as_of = datetime.fromtimestamp(as_of_ts, tz=timezone.utc) if as_of_ts else datetime.now(timezone.utc)
        return {"price": float(price), "as_of": as_of, "source": "yahoo"}
    except Exception as exc:
        logger.warning("Yahoo quote failed for %s (%s): %s", ticker, symbol, exc)
        return None


async def _quote_from_db(db: AsyncSession, asset_id) -> Optional[dict]:
    result = await db.execute(
        select(MarketPrice)
        .where(MarketPrice.asset_id == asset_id)
        .order_by(MarketPrice.timestamp.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    return {"price": float(row.close), "as_of": row.timestamp, "source": "db"}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_twelve_symbol(ticker: str, asset_type: AssetType) -> str:
    normalized = ticker.upper().replace("/", "")
    if asset_type == AssetType.FOREX and len(normalized) == 6 and normalized.isalpha():
        return f"{normalized[:3]}/{normalized[3:]}"
    if asset_type == AssetType.CRYPTO and len(normalized) <= 5 and normalized.isalnum():
        return f"{normalized}/USD"
    return ticker.upper()


def _parse_twelve_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


async def _fundamentals_from_finnhub(ticker: str) -> Optional[dict]:
    if not settings.FINNHUB_API_KEY:
        return None
    ctx = PROVIDERS["finnhub"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://finnhub.io/api/v1/stock/metric",
            params={"symbol": ticker, "metric": "all", "token": settings.FINNHUB_API_KEY},
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        metric = payload.get("metric") or {}
        if not metric:
            return None
        return {
            "market_cap": _safe_float(metric.get("marketCapitalization")),
            "pe_ratio": _safe_float(metric.get("peTTM")),
            "eps": _safe_float(metric.get("epsTTM")),
            "dividend_yield": _safe_float(metric.get("dividendYieldIndicatedAnnual")),
            "week_52_high": _safe_float(metric.get("52WeekHigh")),
            "week_52_low": _safe_float(metric.get("52WeekLow")),
            "as_of": datetime.now(timezone.utc),
            "source": "finnhub",
        }
    except Exception as exc:
        logger.warning("Finnhub fundamentals failed for %s: %s", ticker, exc)
        return None


async def _fundamentals_from_polygon(ticker: str) -> Optional[dict]:
    if not settings.POLYGON_API_KEY:
        return None
    ctx = PROVIDERS["polygon"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://api.polygon.io/v3/reference/tickers/{ticker}",
            params={"apiKey": settings.POLYGON_API_KEY},
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        row = payload.get("results") or {}
        if not row:
            return None
        return {
            "market_cap": _safe_float(row.get("market_cap")),
            "pe_ratio": None,
            "eps": None,
            "dividend_yield": None,
            "week_52_high": None,
            "week_52_low": None,
            "as_of": datetime.now(timezone.utc),
            "source": "polygon",
        }
    except Exception as exc:
        logger.warning("Polygon fundamentals failed for %s: %s", ticker, exc)
        return None


def _bucket_minute(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(second=0, microsecond=0)


async def _persist_quote(db: AsyncSession, asset_id, quote: dict) -> None:
    timestamp = _bucket_minute(quote["as_of"])
    price = float(quote["price"])
    stmt = (
        pg_insert(MarketPrice)
        .values(
            asset_id=asset_id,
            timestamp=timestamp,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=None,
        )
        .on_conflict_do_update(
            index_elements=[MarketPrice.asset_id, MarketPrice.timestamp],
            set_={"high": price, "low": price, "close": price},
        )
    )
    await db.execute(stmt)


class MarketStreamManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._subscription_changed = asyncio.Event()
        self._clients: set[WebSocket] = set()
        self._socket_tickers: dict[WebSocket, set[str]] = {}
        self._ticker_clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._runner_task: Optional[asyncio.Task] = None
        self._provider = "idle"
        self._asset_meta_cache = LRUCache(max_size=500, ttl_seconds=300)
        self._last_persist_at: dict[str, datetime] = {}
        self._prefer_finnhub_until: Optional[datetime] = None
        # Per-client token bucket for WS rate limiting
        self._client_tokens: dict[WebSocket, float] = {}
        self._client_last_refill: dict[WebSocket, float] = {}
        self._ws_rate_limit = 10.0     # messages/sec
        self._ws_bucket_max = 20.0     # max burst

    @property
    def provider(self) -> str:
        return self._provider

    async def start(self) -> None:
        async with self._lock:
            self._ensure_runner_locked()

    async def shutdown(self) -> None:
        async with self._lock:
            task = self._runner_task
            self._runner_task = None
            clients = list(self._clients)
            self._clients.clear()
            self._socket_tickers.clear()
            self._ticker_clients.clear()

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        for websocket in clients:
            with contextlib.suppress(Exception):
                await websocket.close()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
            self._socket_tickers[websocket] = set()
            self._ensure_runner_locked()
            self._subscription_changed.set()

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._remove_socket_locked(websocket)
            self._subscription_changed.set()

    async def get_subscriptions(self, websocket: WebSocket) -> list[str]:
        async with self._lock:
            tickers = set(self._socket_tickers.get(websocket, set()))
        return sorted(tickers)

    async def replace_subscriptions(self, websocket: WebSocket, tickers: list[str]) -> list[str]:
        normalized = self._normalize_tickers(tickers)
        async with self._lock:
            self._remove_socket_locked(websocket)
            self._clients.add(websocket)
            self._socket_tickers[websocket] = set(normalized)
            for ticker in normalized:
                self._ticker_clients[ticker].add(websocket)
            self._ensure_runner_locked()
            self._subscription_changed.set()
            snapshot = set(self._socket_tickers[websocket])
        return sorted(snapshot)

    async def add_subscriptions(self, websocket: WebSocket, tickers: list[str]) -> list[str]:
        normalized = self._normalize_tickers(tickers)
        async with self._lock:
            if websocket not in self._socket_tickers:
                self._clients.add(websocket)
                self._socket_tickers[websocket] = set()
            for ticker in normalized:
                self._socket_tickers[websocket].add(ticker)
                self._ticker_clients[ticker].add(websocket)
            self._ensure_runner_locked()
            self._subscription_changed.set()
            snapshot = set(self._socket_tickers[websocket])
        return sorted(snapshot)

    async def remove_subscriptions(self, websocket: WebSocket, tickers: list[str]) -> list[str]:
        normalized = self._normalize_tickers(tickers)
        async with self._lock:
            current = self._socket_tickers.get(websocket, set())
            for ticker in normalized:
                current.discard(ticker)
                subscribers = self._ticker_clients.get(ticker)
                if subscribers:
                    subscribers.discard(websocket)
                    if not subscribers:
                        self._ticker_clients.pop(ticker, None)
            self._subscription_changed.set()
            snapshot = set(current)
        return sorted(snapshot)

    def _normalize_tickers(self, tickers: list[str]) -> set[str]:
        return {ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()}

    def _remove_socket_locked(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        current = self._socket_tickers.pop(websocket, set())
        for ticker in current:
            subscribers = self._ticker_clients.get(ticker)
            if subscribers:
                subscribers.discard(websocket)
                if not subscribers:
                    self._ticker_clients.pop(ticker, None)

    def _ensure_runner_locked(self) -> None:
        if self._runner_task is None or self._runner_task.done():
            self._runner_task = asyncio.create_task(self._run(), name="market-stream-upstream")

    async def _desired_tickers(self) -> set[str]:
        async with self._lock:
            return set(self._ticker_clients.keys())

    async def _run(self) -> None:
        backoff = 2
        while True:
            tickers = await self._desired_tickers()
            if not tickers:
                self._provider = "idle"
                self._subscription_changed.clear()
                await self._subscription_changed.wait()
                continue

            provider = self._select_provider()
            self._provider = provider
            try:
                if provider == "polygon_ws":
                    await self._run_polygon_ws()
                elif provider == "finnhub_ws":
                    await self._run_finnhub_ws()
                else:
                    await asyncio.sleep(5)
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if provider == "polygon_ws" and settings.FINNHUB_API_KEY:
                    self._prefer_finnhub_until = datetime.now(timezone.utc) + timedelta(minutes=5)
                logger.warning("Market stream upstream error (%s): %s", provider, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _select_provider(self) -> str:
        now = datetime.now(timezone.utc)
        prefer_finnhub = self._prefer_finnhub_until and now < self._prefer_finnhub_until
        if prefer_finnhub and settings.FINNHUB_API_KEY:
            return "finnhub_ws"
        if settings.POLYGON_API_KEY:
            return "polygon_ws"
        if settings.FINNHUB_API_KEY:
            return "finnhub_ws"
        return "none"

    async def _run_polygon_ws(self) -> None:
        try:
            import websockets
        except Exception:
            logger.warning("websockets package not installed; polygon stream disabled")
            await asyncio.sleep(10)
            return

        async with websockets.connect("wss://socket.polygon.io/stocks", ping_interval=20, ping_timeout=20) as upstream:
            await upstream.send(json.dumps({"action": "auth", "params": settings.POLYGON_API_KEY}))
            sent_subscriptions: set[str] = set()

            while True:
                desired = await self._desired_tickers()
                sent_subscriptions = await self._sync_polygon_subscriptions(upstream, desired, sent_subscriptions)
                try:
                    raw = await asyncio.wait_for(upstream.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                for ticker, price, as_of in self._parse_polygon_trades(raw):
                    await self._handle_tick(ticker=ticker, price=price, as_of=as_of, source="polygon_ws")

    async def _run_finnhub_ws(self) -> None:
        try:
            import websockets
        except Exception:
            logger.warning("websockets package not installed; finnhub stream disabled")
            await asyncio.sleep(10)
            return

        url = f"wss://ws.finnhub.io?token={settings.FINNHUB_API_KEY}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as upstream:
            sent_subscriptions: set[str] = set()

            while True:
                desired = await self._desired_tickers()
                sent_subscriptions = await self._sync_finnhub_subscriptions(upstream, desired, sent_subscriptions)
                try:
                    raw = await asyncio.wait_for(upstream.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                for ticker, price, as_of in self._parse_finnhub_trades(raw):
                    await self._handle_tick(ticker=ticker, price=price, as_of=as_of, source="finnhub_ws")

    async def _sync_polygon_subscriptions(self, upstream, desired: set[str], sent: set[str]) -> set[str]:
        to_subscribe = desired - sent
        to_unsubscribe = sent - desired
        if to_subscribe:
            params = ",".join(f"T.{ticker}" for ticker in sorted(to_subscribe))
            await upstream.send(json.dumps({"action": "subscribe", "params": params}))
        if to_unsubscribe:
            params = ",".join(f"T.{ticker}" for ticker in sorted(to_unsubscribe))
            await upstream.send(json.dumps({"action": "unsubscribe", "params": params}))
        return desired

    async def _sync_finnhub_subscriptions(self, upstream, desired: set[str], sent: set[str]) -> set[str]:
        to_subscribe = desired - sent
        to_unsubscribe = sent - desired
        for ticker in sorted(to_subscribe):
            await upstream.send(json.dumps({"type": "subscribe", "symbol": ticker}))
        for ticker in sorted(to_unsubscribe):
            await upstream.send(json.dumps({"type": "unsubscribe", "symbol": ticker}))
        return desired

    def _parse_polygon_trades(self, raw: Any) -> list[tuple[str, float, datetime]]:
        try:
            payload = json.loads(raw)
        except Exception:
            return []

        events = payload if isinstance(payload, list) else [payload]
        parsed: list[tuple[str, float, datetime]] = []
        for event in events:
            if not isinstance(event, dict) or event.get("ev") != "T":
                continue
            ticker = str(event.get("sym") or "").upper()
            price = event.get("p")
            if not ticker or price is None:
                continue
            as_of = self._from_epoch(event.get("t"))
            parsed.append((ticker, float(price), as_of))
        return parsed

    def _parse_finnhub_trades(self, raw: Any) -> list[tuple[str, float, datetime]]:
        try:
            payload = json.loads(raw)
        except Exception:
            return []

        if payload.get("type") != "trade":
            return []

        parsed: list[tuple[str, float, datetime]] = []
        for row in payload.get("data") or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("s") or "").upper()
            price = row.get("p")
            if not ticker or price is None:
                continue
            as_of = self._from_epoch(row.get("t"))
            parsed.append((ticker, float(price), as_of))
        return parsed

    def _from_epoch(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        try:
            epoch = float(value)
        except Exception:
            return datetime.now(timezone.utc)

        if epoch > 1_000_000_000_000_000:
            epoch /= 1_000_000_000
        elif epoch > 1_000_000_000_000:
            epoch /= 1000
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    async def _handle_tick(self, ticker: str, price: float, as_of: datetime, source: str) -> None:
        currency = await self._get_currency_for_ticker(ticker)
        payload = {
            "type": "price_update",
            "ticker": ticker,
            "price": float(price),
            "currency": currency,
            "as_of": _to_iso(as_of),
            "source": source,
        }
        await self._cache_tick_quote(payload)
        await self._broadcast_ticker(ticker, payload)
        await self._maybe_persist_tick(ticker=ticker, price=float(price), as_of=as_of, source=source)

    async def _broadcast_ticker(self, ticker: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._ticker_clients.get(ticker, set()))

        disconnected: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(payload)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            await self.disconnect(websocket)

    async def _cache_tick_quote(self, payload: dict[str, Any]) -> None:
        key = _quote_cache_key(payload["ticker"])
        cache_payload = {
            "price": payload["price"],
            "currency": payload["currency"],
            "as_of": payload["as_of"],
            "source": payload["source"],
        }
        with contextlib.suppress(Exception):
            await _cache_set_json(key, cache_payload, ttl_seconds=REALTIME_PRICE_TTL_SECONDS)

    async def _maybe_persist_tick(self, ticker: str, price: float, as_of: datetime, source: str) -> None:
        now = datetime.now(timezone.utc)
        last = self._last_persist_at.get(ticker)
        if last and (now - last).total_seconds() < 15:
            return

        meta = await self._get_asset_meta(ticker)
        if not meta:
            return

        quote = {"price": price, "as_of": as_of, "source": source}
        try:
            async with AsyncSessionFactory() as db:
                await _persist_quote(db, meta["asset_id"], quote)
                await db.commit()
            self._last_persist_at[ticker] = now
        except Exception as exc:
            logger.debug("Tick persist failed for %s: %s", ticker, exc)

    async def _get_asset_meta(self, ticker: str) -> Optional[dict[str, Any]]:
        cached = self._asset_meta_cache.get(ticker)
        if cached:
            return cached

        async with AsyncSessionFactory() as db:
            result = await db.execute(select(Asset.id, Asset.currency).where(Asset.ticker == ticker))
            row = result.first()
            if not row:
                return None
            meta = {"asset_id": row[0], "currency": row[1] or "USD"}
            self._asset_meta_cache.set(ticker, meta)
            return meta

    async def _get_currency_for_ticker(self, ticker: str) -> str:
        meta = await self._get_asset_meta(ticker)
        if not meta:
            return "USD"
        return str(meta.get("currency") or "USD")


market_stream_manager = MarketStreamManager()


async def get_quote(db: AsyncSession, ticker: str, refresh: bool = False) -> QuoteOut:
    ticker_upper = ticker.upper()
    key = _quote_cache_key(ticker_upper)
    if not refresh:
        cached = await _cache_get_json(key)
        if cached and cached.get("source") != "synthetic":
            return QuoteOut(
                ticker=ticker_upper,
                price=float(cached["price"]),
                currency=cached["currency"],
                as_of=_from_iso(cached["as_of"]),
                source=cached["source"],
                cache_hit=True,
            )

    asset = await _get_asset_or_404(db, ticker_upper)
    ticker_to_fetch = asset.ticker
    quote: Optional[dict] = None

    if asset.asset_type in {AssetType.STOCK, AssetType.ETF, AssetType.INDEX, AssetType.COMMODITY, AssetType.FOREX}:
        quote = await _quote_from_yahoo(ticker_to_fetch, asset.asset_type)
        if quote is None:
            quote = await _quote_from_finnhub(ticker_to_fetch)
        if quote is None:
            quote = await _quote_from_polygon(ticker_to_fetch)
        if quote is None:
            quote = await _quote_from_alpaca(ticker_to_fetch)
        if quote is None:
            quote = await _quote_from_fcsapi(ticker_to_fetch)
        if quote is None:
            quote = await _quote_from_twelve_data(ticker_to_fetch, asset.asset_type)
    elif asset.asset_type == AssetType.CRYPTO:
        quote = await _quote_from_binance(ticker_to_fetch)
        if quote is None:
            quote = await _quote_from_yahoo(ticker_to_fetch, asset.asset_type)
        if quote is None:
            quote = await _quote_from_twelve_data(ticker_to_fetch, asset.asset_type)

    if quote is not None:
        await _persist_quote(db, asset.id, quote)

    if quote is None and _require_live_api():
        raise HTTPException(
            status_code=503,
            detail=f"Live quote provider unavailable for '{ticker_to_fetch}'",
        )

    if quote is None:
        quote = await _quote_from_db(db, asset.id)

    if quote is None:
        raise HTTPException(status_code=404, detail=f"No quote data available for '{ticker_to_fetch}'")

    cache_payload = {
        "price": quote["price"],
        "currency": asset.currency,
        "as_of": _to_iso(quote["as_of"]),
        "source": quote["source"],
    }
    await _cache_set_json(key, cache_payload, ttl_seconds=REALTIME_PRICE_TTL_SECONDS)

    return QuoteOut(
        ticker=ticker_to_fetch,
        price=float(quote["price"]),
        currency=asset.currency,
        as_of=quote["as_of"],
        source=quote["source"],
        cache_hit=False,
    )


async def _ohlcv_from_eodhd(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    if not getattr(settings, "EODHD_API_KEY", None):
        return None
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(limit * 3, 30))
    ctx = PROVIDERS["eodhd"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://eodhd.com/api/eod/{ticker}.US",
            params={
                "api_token": settings.EODHD_API_KEY,
                "fmt": "json",
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
            },
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return None
        points = [
            OHLCVPointOut(
                timestamp=datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                open=_safe_float(row.get("open")),
                high=_safe_float(row.get("high")),
                low=_safe_float(row.get("low")),
                close=_safe_float(row.get("close")),
                volume=_safe_float(row.get("volume"))
            )
            for row in payload
            if row.get("date") and row.get("close")
        ]
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("EODHD OHLCV failed for %s: %s", ticker, exc)
        return None

async def _ohlcv_from_binance(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    symbol = ticker.replace("-", "").replace("/", "").upper()
    if symbol.endswith("USD"):
        symbol = symbol[:-3] + "USDT"
    ctx = PROVIDERS["binance"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1d", "limit": limit},
        )
        if response is None or response.status_code != 200:
            return None
        rows = response.json()
        points: list[OHLCVPointOut] = []
        for row in rows:
            timestamp = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            points.append(
                OHLCVPointOut(
                    timestamp=timestamp, open=_safe_float(row[1]), high=_safe_float(row[2]),
                    low=_safe_float(row[3]), close=_safe_float(row[4]), volume=_safe_float(row[5])
                )
            )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("Binance OHLCV failed for %s (%s): %s", ticker, symbol, exc)
        return None

async def _ohlcv_from_alpha_vantage(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    if not getattr(settings, "ALPHA_VANTAGE_API_KEY", None):
        return None
    ctx = PROVIDERS["alphavantage"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker,
                "outputsize": "compact" if limit <= 100 else "full",
                "apikey": settings.ALPHA_VANTAGE_API_KEY
            },
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        # Detect rate-limit message returned as 200 JSON (AV free tier 25 req/day)
        if "Note" in payload or "Information" in payload:
            logger.warning("AlphaVantage OHLCV rate limit hit for %s", ticker)
            return None
        time_series = payload.get("Time Series (Daily)", {})
        if not time_series:
            return None
        
        points: list[OHLCVPointOut] = []
        for date_str, values in time_series.items():
            timestamp = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            points.append(
                OHLCVPointOut(
                    timestamp=timestamp, open=_safe_float(values.get("1. open")),
                    high=_safe_float(values.get("2. high")), low=_safe_float(values.get("3. low")),
                    close=_safe_float(values.get("4. close")), volume=_safe_float(values.get("5. volume"))
                )
            )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("AlphaVantage OHLCV failed for %s: %s", ticker, exc)
        return None


async def _ohlcv_from_alpaca(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    """Alpaca Market Data API — free Basic plan: 1-year+ historical daily bars for US equities."""
    if not getattr(settings, "ALPACA_API_KEY_ID", None) or not getattr(settings, "ALPACA_API_SECRET_KEY", None):
        return None
    ctx = PROVIDERS["alpaca"]
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(limit * 2, 30))
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
            params={
                "timeframe": "1Day",
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                # Alpaca returns bars ascending from `start` and pages at `limit`, so a
                # limit of `limit` would hand back the OLDEST bars in the window and drop
                # the most recent weeks. Ask for the whole window (capped at Alpaca's
                # 10000 max) and take the newest `limit` after sorting below.
                "limit": min(max(limit * 2, 100), 10000),
                "adjustment": "split",
                "feed": "iex",
            },
            headers={
                "APCA-API-KEY-ID": settings.ALPACA_API_KEY_ID,
                "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET_KEY,
            },
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        bars = payload.get("bars") or []
        if not bars:
            return None
        points: list[OHLCVPointOut] = []
        for bar in bars:
            t_str = bar.get("t")
            if not t_str:
                continue
            try:
                ts = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            points.append(
                OHLCVPointOut(
                    timestamp=ts,
                    open=_safe_float(bar.get("o")),
                    high=_safe_float(bar.get("h")),
                    low=_safe_float(bar.get("l")),
                    close=_safe_float(bar.get("c")),
                    volume=_safe_float(bar.get("v")),
                )
            )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("Alpaca OHLCV failed for %s: %s", ticker, exc)
        return None


async def _ohlcv_from_yahoo(ticker: str, asset_type: AssetType, limit: int) -> Optional[list[OHLCVPointOut]]:
    """Yahoo Finance chart endpoint — free, no API key, daily bars for any asset type.
    Gap-fill + final fallback, mirroring `_quote_from_yahoo`'s position in the chain."""
    symbol = _yahoo_symbol(ticker, asset_type)
    ctx = PROVIDERS["yahoo"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "1y", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response is None or response.status_code != 200:
            return None
        results = response.json().get("chart", {}).get("result") or []
        if not results:
            return None
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        points: list[OHLCVPointOut] = []
        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue
            points.append(
                OHLCVPointOut(
                    timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=_safe_float(opens[i]) if i < len(opens) else None,
                    high=_safe_float(highs[i]) if i < len(highs) else None,
                    low=_safe_float(lows[i]) if i < len(lows) else None,
                    close=float(close),
                    volume=_safe_float(volumes[i]) if i < len(volumes) else None,
                )
            )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("Yahoo OHLCV failed for %s (%s): %s", ticker, symbol, exc)
        return None


async def _ohlcv_from_fcsapi(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    if not getattr(settings, "FCS_API_KEY", None):
        return None
    ctx = PROVIDERS["fcs"]
    try:
        symbol = _normalize_twelve_symbol(ticker, AssetType.FOREX) 
        response = await ctx.execute(
            global_http_client.get,
            "https://fcsapi.com/api-v3/forex/history",
            params={
                "symbol": symbol,
                "period": "1d",
                "access_key": settings.FCS_API_KEY,
            },
        )
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        if not payload.get("status"):
            return None
        
        rows = payload.get("response", {}).get(symbol, [])
        if not rows:
            return None
            
        points = []
        for row in rows:
            if row.get("t"):
                timestamp = datetime.fromtimestamp(int(row["t"]), tz=timezone.utc)
                points.append(
                    OHLCVPointOut(
                        timestamp=timestamp,
                        open=_safe_float(row.get("o")),
                        high=_safe_float(row.get("h")),
                        low=_safe_float(row.get("l")),
                        close=_safe_float(row.get("c")),
                        volume=_safe_float(row.get("v"))
                    )
                )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("FCS API OHLCV failed for %s: %s", ticker, exc)
        return None


async def _ohlcv_from_finnhub(ticker: str, limit: int) -> Optional[list[OHLCVPointOut]]:
    # Finnhub OHLCV (candle) is restricted on the free tier, disabling to prevent 403s
    return None


async def _ohlcv_from_twelve_data(
    ticker: str,
    limit: int,
    asset_type: AssetType,
) -> Optional[list[OHLCVPointOut]]:
    if not settings.TWELVEDATA_API_KEY:
        return None
    symbol = _normalize_twelve_symbol(ticker, asset_type)
    ctx = PROVIDERS["twelvedata"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": max(1, min(limit, 365)),
                "apikey": settings.TWELVEDATA_API_KEY,
                "format": "JSON",
            },
        )
        if response is None:
            return None
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("values") or []
        if not rows:
            return None

        points: list[OHLCVPointOut] = []
        for row in rows[:limit]:
            timestamp = _parse_twelve_datetime(row.get("datetime"))
            close = _safe_float(row.get("close"))
            if timestamp is None or close is None:
                continue
            points.append(
                OHLCVPointOut(
                    timestamp=timestamp,
                    open=_safe_float(row.get("open")),
                    high=_safe_float(row.get("high")),
                    low=_safe_float(row.get("low")),
                    close=close,
                    volume=_safe_float(row.get("volume")),
                )
            )
        points.sort(key=lambda p: p.timestamp, reverse=True)
        return points[:limit] if points else None
    except Exception as exc:
        logger.warning("TwelveData OHLCV failed for %s (%s): %s", ticker, symbol, exc)
        return None


async def _ohlcv_from_db(db: AsyncSession, asset_id, limit: int) -> list[OHLCVPointOut]:
    result = await db.execute(
        select(MarketPrice)
        .where(MarketPrice.asset_id == asset_id)
        .order_by(MarketPrice.timestamp.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        OHLCVPointOut(
            timestamp=row.timestamp,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in rows
    ]


async def _persist_ohlcv(db: AsyncSession, asset_id, points: list[OHLCVPointOut]) -> None:
    if not points:
        return

    values = [
        {
            "asset_id": asset_id,
            "timestamp": point.timestamp.astimezone(timezone.utc),
            "open": point.open,
            "high": point.high,
            "low": point.low,
            "close": point.close,
            "volume": point.volume,
        }
        for point in points
    ]
    insert_stmt = pg_insert(MarketPrice).values(values)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[MarketPrice.asset_id, MarketPrice.timestamp],
        set_={
            "open": insert_stmt.excluded.open,
            "high": insert_stmt.excluded.high,
            "low": insert_stmt.excluded.low,
            "close": insert_stmt.excluded.close,
            "volume": insert_stmt.excluded.volume,
        },
    )
    await db.execute(stmt)


async def get_ohlcv(
    db: AsyncSession,
    ticker: str,
    interval: str = "1day",
    limit: int = 100,
    refresh: bool = False,
) -> OHLCVOut:
    if interval != "1day":
        raise HTTPException(status_code=422, detail="Only interval='1day' is currently supported")

    ticker_upper = ticker.upper()
    key = _ohlcv_cache_key(ticker_upper, interval, limit)
    if not refresh:
        cached = await _cache_get_json(key)
        if cached and cached.get("source") != "synthetic":
            points = [
                OHLCVPointOut(
                    timestamp=_from_iso(point["timestamp"]),
                    open=point.get("open"),
                    high=point.get("high"),
                    low=point.get("low"),
                    close=point["close"],
                    volume=point.get("volume"),
                )
                for point in cached["points"]
            ]
            return OHLCVOut(
                ticker=ticker_upper,
                interval=interval,
                points=points,
                source=cached["source"],
                cache_hit=True,
            )

    asset = await _get_asset_or_404(db, ticker_upper)
    # Fetch under the RESOLVED symbol. `ticker_upper` is raw user input (it may be a
    # company name, or a symbol that resolved to a different asset) while the points
    # below are persisted under `asset.id`; fetching by anything else would write one
    # instrument price history into the rows of another.
    ticker_to_fetch = asset.ticker
    points: list[OHLCVPointOut] = []
    source = "db"

    if asset.asset_type in {AssetType.STOCK, AssetType.ETF, AssetType.INDEX, AssetType.COMMODITY, AssetType.FOREX}:
        yahoo_points = await _ohlcv_from_yahoo(ticker_to_fetch, asset.asset_type, limit=limit)
        if yahoo_points:
            points = yahoo_points
            source = "yahoo"
        else:
            eodhd_points = await _ohlcv_from_eodhd(ticker_to_fetch, limit=limit)
            if eodhd_points:
                points = eodhd_points
                source = "eodhd"
            else:
                alpaca_points = await _ohlcv_from_alpaca(ticker_to_fetch, limit=limit)
                if alpaca_points:
                    points = alpaca_points
                    source = "alpaca"
                else:
                    twelve_points = await _ohlcv_from_twelve_data(
                        ticker_to_fetch,
                        limit=limit,
                        asset_type=asset.asset_type,
                    )
                    if twelve_points:
                        points = twelve_points
                        source = "twelve_data"
    elif asset.asset_type == AssetType.CRYPTO:
        binance_points = await _ohlcv_from_binance(ticker_to_fetch, limit=limit)
        if binance_points:
            points = binance_points
            source = "binance"
        else:
            yahoo_points = await _ohlcv_from_yahoo(ticker_to_fetch, asset.asset_type, limit=limit)
            if yahoo_points:
                points = yahoo_points
                source = "yahoo"
            else:
                twelve_points = await _ohlcv_from_twelve_data(
                    ticker_to_fetch,
                    limit=limit,
                    asset_type=asset.asset_type,
                )
                if twelve_points:
                    points = twelve_points
                    source = "twelve_data"

    if points and source in {"eodhd", "alpaca", "fcsapi", "finnhub", "twelve_data", "alphavantage", "binance", "yahoo"}:
        await _persist_ohlcv(db, asset.id, points)

    if not points and _require_live_api():
        raise HTTPException(
            status_code=503,
            detail=f"Live OHLCV provider unavailable for '{ticker_upper}'",
        )

    if not points:
        points = await _ohlcv_from_db(db, asset.id, limit=limit)
        source = "db"

    if not points:
        raise HTTPException(status_code=404, detail=f"No OHLCV data available for '{ticker_upper}'")

    cache_payload = {
        "source": source,
        "points": [
            {
                "timestamp": _to_iso(point.timestamp),
                "open": point.open,
                "high": point.high,
                "low": point.low,
                "close": point.close,
                "volume": point.volume,
            }
            for point in points
        ],
    }
    await _cache_set_json(key, cache_payload, ttl_seconds=DAILY_OHLCV_TTL_SECONDS)

    return OHLCVOut(
        ticker=ticker_upper,
        interval=interval,
        points=points,
        source=source,
        cache_hit=False,
    )


async def get_historical_1y(db: AsyncSession, ticker: str, refresh: bool = False) -> OHLCVOut:
    ticker_upper = ticker.upper()
    key = _historical_1y_cache_key(ticker_upper)
    if not refresh:
        cached = await _cache_get_json(key)
        if cached and cached.get("source") != "synthetic":
            points = [
                OHLCVPointOut(
                    timestamp=_from_iso(point["timestamp"]),
                    open=point.get("open"),
                    high=point.get("high"),
                    low=point.get("low"),
                    close=point["close"],
                    volume=point.get("volume"),
                )
                for point in cached["points"]
            ]
            return OHLCVOut(
                ticker=ticker_upper,
                interval="1day",
                points=points,
                source=cached.get("source", "db"),
                cache_hit=True,
            )

    ohlcv = await get_ohlcv(db, ticker=ticker_upper, interval="1day", limit=365, refresh=refresh)
    cache_payload = {
        "source": ohlcv.source,
        "points": [
            {
                "timestamp": _to_iso(point.timestamp),
                "open": point.open,
                "high": point.high,
                "low": point.low,
                "close": point.close,
                "volume": point.volume,
            }
            for point in ohlcv.points
        ],
    }
    await _cache_set_json(key, cache_payload, ttl_seconds=HISTORICAL_1Y_TTL_SECONDS)
    return OHLCVOut(
        ticker=ohlcv.ticker,
        interval=ohlcv.interval,
        points=ohlcv.points,
        source=ohlcv.source,
        cache_hit=False,
    )


async def get_fundamentals(db: AsyncSession, ticker: str, refresh: bool = False) -> FundamentalsOut:
    ticker_upper = ticker.upper()
    key = _fundamentals_cache_key(ticker_upper)
    if not refresh:
        cached = await _cache_get_json(key)
        if cached and cached.get("source") != "synthetic":
            return FundamentalsOut(
                ticker=ticker_upper,
                currency=cached["currency"],
                market_cap=cached.get("market_cap"),
                pe_ratio=cached.get("pe_ratio"),
                eps=cached.get("eps"),
                dividend_yield=cached.get("dividend_yield"),
                week_52_high=cached.get("week_52_high"),
                week_52_low=cached.get("week_52_low"),
                as_of=_from_iso(cached["as_of"]),
                source=cached.get("source", "cache"),
                cache_hit=True,
            )

    asset = await _get_asset_or_404(db, ticker_upper)
    fundamentals: Optional[dict] = None

    if asset.asset_type in {AssetType.STOCK, AssetType.ETF, AssetType.INDEX}:
        fundamentals = await _fundamentals_from_finnhub(ticker_upper)
        if fundamentals is None:
            fundamentals = await _fundamentals_from_polygon(ticker_upper)

    if fundamentals is None:
        status_code = 503 if _require_live_api() else 404
        raise HTTPException(
            status_code=status_code,
            detail=f"Live fundamentals provider unavailable for '{ticker_upper}'",
        )

    cache_payload = {
        "currency": asset.currency,
        "market_cap": fundamentals.get("market_cap"),
        "pe_ratio": fundamentals.get("pe_ratio"),
        "eps": fundamentals.get("eps"),
        "dividend_yield": fundamentals.get("dividend_yield"),
        "week_52_high": fundamentals.get("week_52_high"),
        "week_52_low": fundamentals.get("week_52_low"),
        "as_of": _to_iso(fundamentals["as_of"]),
        "source": fundamentals["source"],
    }
    await _cache_set_json(key, cache_payload, ttl_seconds=FUNDAMENTALS_TTL_SECONDS)

    return FundamentalsOut(
        ticker=ticker_upper,
        currency=asset.currency,
        market_cap=fundamentals.get("market_cap"),
        pe_ratio=fundamentals.get("pe_ratio"),
        eps=fundamentals.get("eps"),
        dividend_yield=fundamentals.get("dividend_yield"),
        week_52_high=fundamentals.get("week_52_high"),
        week_52_low=fundamentals.get("week_52_low"),
        as_of=fundamentals["as_of"],
        source=fundamentals["source"],
        cache_hit=False,
    )
