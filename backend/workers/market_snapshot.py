"""
GeoAtlas — High-Performance Market Snapshot Engine
====================================================
Priority-based asset fetching, adaptive rate limiting via ProviderContext,
soft-timeout ingestion, DB batch buffer, and last-good fallback.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import List, Dict
from collections import Counter

from core.database import AsyncSessionFactory
from core.http import global_http_client, PROVIDERS, DBBuffer
from core.market_cache import set_market_snapshot, get_market_snapshot
from modules.market.models import Asset, AssetType, MarketPrice
from core.config import settings
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# ─── CONSTANTS ───────────────────────────────────────────────────────────────

SNAPSHOT_INTERVAL = 30          # seconds
ASSET_CACHE_TTL = 300           # 5 min
MAX_STALE_SNAPSHOT_SEC = 120    # last-good fallback TTL
PROVIDER_TASK_TIMEOUT = 5.0     # per-provider soft timeout

# Priority ticker sets
HIGH_PRIORITY_TICKERS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",  # Crypto
    "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN",                  # Equities
}

# ─── DB BATCH BUFFER ─────────────────────────────────────────────────────────

async def _flush_price_batch(batch: list[dict]) -> None:
    """Bulk upsert MarketPrice records."""
    if not batch:
        return
    async with AsyncSessionFactory() as db:
        stmt = pg_insert(MarketPrice).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketPrice.asset_id, MarketPrice.timestamp],
            set_={
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
            },
        )
        await db.execute(stmt)
        await db.commit()
    logger.debug("[DB] Flushed %d price records", len(batch))

db_buffer = DBBuffer(
    flush_fn=_flush_price_batch,
    interval=1.0,
    batch_size=50,
    max_queue=5000,
)

# ─── ASSET CACHE ─────────────────────────────────────────────────────────────

_asset_cache: list[Asset] = []
_asset_cache_ts: float = 0.0

async def _get_cached_assets() -> list[Asset]:
    global _asset_cache, _asset_cache_ts
    now = time.time()
    if _asset_cache and (now - _asset_cache_ts) < ASSET_CACHE_TTL:
        return _asset_cache
    async with AsyncSessionFactory() as db:
        result = await db.execute(select(Asset).execution_options(populate_existing=True))
        _asset_cache = list(result.scalars().all())
        _asset_cache_ts = now
    logger.info("[SNAPSHOT] Assets refreshed: %d", len(_asset_cache))
    return _asset_cache


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def normalize_price(data, source):
    ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return {
        "price": float(data.get("price")),
        "change": float(data.get("change", 0.0)),
        "source": source,
        "as_of": data.get("as_of") or ts.isoformat(),
    }


def choose_best(*candidates):
    for c in candidates:
        if c and c.get("price"):
            return c
    return None


def is_market_closed():
    now = datetime.now(timezone.utc).hour
    return now < 13 or now > 20


def normalize_forex(ticker):
    if len(ticker) == 6:
        return f"{ticker[:3]}/{ticker[3:]}"
    return ticker


def normalize_crypto_ticker(ticker: str):
    t = ticker.upper().replace("-", "").replace("/", "")
    if t.endswith("USD"):
        t = t[:-3]
    return f"{t}USDT"


# ─── PROVIDERS (using global client + ProviderContext) ───────────────────────

async def fetch_binance_bulk():
    ctx = PROVIDERS["binance"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.binance.com/api/v3/ticker/24hr",
        )
        if response is None:
            return {"status": "stale", "data": {}}
        response.raise_for_status()
        data = response.json()
        return {
            "status": "live",
            "data": {
                item["symbol"]: normalize_price(
                    {"price": item["lastPrice"], "change": item["priceChangePercent"]},
                    "binance",
                )
                for item in data
                if "symbol" in item
            },
        }
    except Exception as e:
        logger.warning(f"Binance fetch failed: {e}")
        return {"status": "stale", "data": {}}


async def fetch_polygon_per_ticker(tickers: list):
    if not settings.POLYGON_API_KEY or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["polygon"]
    out = {}

    async def fetch_one(ticker):
        try:
            response = await ctx.execute(
                global_http_client.get,
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
                params={"apiKey": settings.POLYGON_API_KEY},
            )
            if response is None:
                return
            if response.status_code == 200:
                data = response.json()
                results = data.get("results")
                if results:
                    out[ticker] = normalize_price({"price": results[0]["c"]}, "polygon")
        except Exception as e:
            logger.debug(f"Polygon failed for {ticker}: {e}")

    await asyncio.gather(*(fetch_one(t) for t in tickers))
    return {"status": "live" if out else "stale", "data": out}


async def fetch_finnhub_per_ticker(tickers: list):
    if not getattr(settings, "FINNHUB_API_KEY", None) or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["finnhub"]
    out = {}

    async def fetch_one(ticker):
        try:
            response = await ctx.execute(
                global_http_client.get,
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": settings.FINNHUB_API_KEY},
            )
            if response is None:
                return
            if response.status_code == 200:
                data = response.json()
                price = data.get("c")
                if price and float(price) > 0:
                    out[ticker] = normalize_price({"price": price}, "finnhub")
        except Exception as e:
            logger.debug(f"Finnhub failed for {ticker}: {e}")

    await asyncio.gather(*(fetch_one(t) for t in tickers))
    return {"status": "live" if out else "stale", "data": out}


async def fetch_twelvedata_batch(tickers: List[str]):
    if not settings.TWELVEDATA_API_KEY or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["twelvedata"]
    try:
        response = await ctx.execute(
            global_http_client.get,
            "https://api.twelvedata.com/price",
            params={
                "symbol": ",".join(tickers[:12]),
                "apikey": settings.TWELVEDATA_API_KEY,
            },
        )
        if response is None:
            return {"status": "stale", "data": {}}
        if response.status_code == 429:
            logger.warning("[TWELVEDATA] Batch rate limited")
            return {"status": "stale", "data": {}}
        response.raise_for_status()
        payload = response.json()

        out = {}
        if "price" in payload:
            out[tickers[0]] = normalize_price({"price": payload["price"]}, "twelvedata")
        else:
            for sym, val in payload.items():
                if isinstance(val, dict) and "price" in val:
                    out[sym] = normalize_price({"price": val["price"]}, "twelvedata")
        return {"status": "live", "data": out}
    except Exception as e:
        logger.warning(f"TwelveData fetch failed: {e}")
        return {"status": "stale", "data": {}}


async def fetch_fcs_api_batch(tickers: List[str]):
    if not getattr(settings, "FCS_API_KEY", None) or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["fcs"]
    out = {}
    try:
        fcs_symbols = [t.replace("/", "") for t in tickers]
        response = await ctx.execute(
            global_http_client.get,
            "https://fcsapi.com/api-v3/forex/latest",
            params={"symbol": ",".join(fcs_symbols), "access_key": settings.FCS_API_KEY},
        )
        if response and response.status_code == 200:
            payload = response.json()
            if payload.get("status"):
                for row in payload.get("response", []):
                    sym = normalize_forex(row["s"])
                    out[sym] = normalize_price({"price": row["c"]}, "fcs")
    except Exception as e:
        logger.debug(f"FCS fetch failed: {e}")
    return {"status": "live" if out else "stale", "data": out}


async def fetch_eodhd_batch(tickers: List[str]):
    if not getattr(settings, "EODHD_API_KEY", None) or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["eodhd"]
    out = {}
    try:
        url = f"https://eodhd.com/api/real-time/{tickers[0]}.US"
        params = {"api_token": settings.EODHD_API_KEY, "fmt": "json"}
        if len(tickers) > 1:
            params["s"] = ",".join([t + ".US" for t in tickers[1:]])
        response = await ctx.execute(global_http_client.get, url, params=params)
        if response and response.status_code == 200:
            payload = response.json()
            data_list = payload if isinstance(payload, list) else [payload]
            for row in data_list:
                raw_sym = row.get("code", "")
                sym = raw_sym.split(".")[0]
                if sym and row.get("close"):
                    out[sym] = normalize_price({"price": row["close"]}, "eodhd")
    except Exception as e:
        logger.debug(f"EODHD fetch failed: {e}")
    return {"status": "live" if out else "stale", "data": out}


async def fetch_alpha_vantage_per_ticker(tickers: list):
    if not getattr(settings, "ALPHA_VANTAGE_API_KEY", None) or not tickers:
        return {"status": "disabled", "data": {}}
    ctx = PROVIDERS["alphavantage"]
    out = {}

    async def fetch_one(ticker):
        try:
            response = await ctx.execute(
                global_http_client.get,
                "https://www.alphavantage.co/query",
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": ticker,
                    "apikey": settings.ALPHA_VANTAGE_API_KEY,
                },
            )
            if response and response.status_code == 200:
                data = response.json()
                quote = data.get("Global Quote", {})
                price = quote.get("05. price")
                if price:
                    out[ticker] = normalize_price({"price": price}, "alphavantage")
        except Exception as e:
            logger.debug(f"AlphaVantage failed for {ticker}: {e}")

    await asyncio.gather(*(fetch_one(t) for t in tickers))
    return {"status": "live" if out else "stale", "data": out}


# ── INTELLIGENCE ENGINE ─────────────────────────────────────────────────────

async def fetch_intelligence_map():
    async with AsyncSessionFactory() as db:
        query = text("""
            SELECT DISTINCT ON (ei.asset_id)
                ei.asset_id,
                e.title,
                ei.impact_direction,
                LEAST(1.0,
                    (COALESCE(e.severity,1)/5.0) *
                    (0.6 * COALESCE(ei.impact_strength,0.5)
                    + 0.4 * COALESCE(e.confidence_score,0.5))
                ) AS impact_score
            FROM event_impacts ei
            JOIN events e ON e.id = ei.event_id
            WHERE e.status::text != 'rejected'
            ORDER BY ei.asset_id, e.created_at DESC;
        """)
        result = await db.execute(query)
        rows = result.fetchall()
        logger.info(f"Intelligence rows fetched: {len(rows)}")
        return {
            str(row.asset_id): {
                "impact_score": float(row.impact_score or 0.0),
                "direction": row.impact_direction,
                "tag": row.title,
            }
            for row in rows
        }


def apply_intelligence(snapshot: list, intelligence_map: Dict):
    for item in snapshot:
        intel = intelligence_map.get(str(item["id"]))
        if intel:
            item["tag"] = intel["tag"]
            item["impact_score"] = intel["impact_score"]
            item["risk"] = (
                "high"
                if intel["direction"] == "negative" and intel["impact_score"] > 0.6
                else "low"
            )
        else:
            item["impact_score"] = 0.0
    return snapshot


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────

_snapshot_version = 0

async def run_snapshot_loop():
    global _snapshot_version
    logger.info("Market snapshot worker started")
    print("[SNAPSHOT WORKER] Started and entering loop!")

    # Staggered warmup — avoid cold-start rate-limit spikes
    await asyncio.sleep(random.uniform(0, 1.5))

    cycle = 0
    next_tick = time.time()

    while True:
        next_tick += SNAPSHOT_INTERVAL
        cycle += 1
        t0 = time.perf_counter()

        logger.info("Snapshot loop running (cycle %d)...", cycle)
        try:
            # 1. Asset cache (refreshed every 5 min)
            assets = await _get_cached_assets()
            logger.info(f"[SNAPSHOT] Assets: {len(assets)}")

            # 2. Classify tickers by priority
            equity_tickers_high = []
            equity_tickers_low = []
            forex_tickers = []

            for a in assets:
                t = a.ticker.upper()
                if a.asset_type in {AssetType.STOCK, AssetType.ETF}:
                    if t in HIGH_PRIORITY_TICKERS:
                        equity_tickers_high.append(t)
                    else:
                        equity_tickers_low.append(t)
                elif a.asset_type == AssetType.FOREX:
                    forex_tickers.append(normalize_forex(t))

            # Priority scheduling: LOW tickers only on every 4th cycle
            fetch_equities = equity_tickers_high[:]
            if cycle % 2 == 0:
                fetch_equities.extend(equity_tickers_low[:len(equity_tickers_low) // 2])
            if cycle % 4 == 0:
                fetch_equities.extend(equity_tickers_low[len(equity_tickers_low) // 2:])

            # 3. Fetch providers with soft-timeout (asyncio.wait)
            provider_tasks = {
                "binance": asyncio.create_task(fetch_binance_bulk()),
                "polygon": asyncio.create_task(fetch_polygon_per_ticker(fetch_equities)),
                "eodhd": asyncio.create_task(fetch_eodhd_batch(fetch_equities)),
                "finnhub": asyncio.create_task(fetch_finnhub_per_ticker(fetch_equities)),
                "alphavantage": asyncio.create_task(fetch_alpha_vantage_per_ticker(fetch_equities)),
                "fcs": asyncio.create_task(fetch_fcs_api_batch(forex_tickers)),
                "twelvedata": asyncio.create_task(fetch_twelvedata_batch(fetch_equities + forex_tickers)),
            }

            done, pending = await asyncio.wait(
                provider_tasks.values(),
                timeout=PROVIDER_TASK_TIMEOUT,
            )

            # Cancel any stragglers
            for task in pending:
                task.cancel()
                logger.warning("[SNAPSHOT] Provider task timed out and was cancelled")

            # Collect results (use empty dict for timed-out providers)
            results = {}
            for name, task in provider_tasks.items():
                if task in done and not task.cancelled():
                    try:
                        results[name] = task.result()
                    except Exception:
                        results[name] = {"status": "stale", "data": {}}
                else:
                    results[name] = {"status": "stale", "data": {}}

            binance_res = results["binance"]
            polygon_res = results["polygon"]
            eodhd_res = results["eodhd"]
            finnhub_res = results["finnhub"]
            alpha_vantage_res = results["alphavantage"]
            fcs_res = results["fcs"]
            twelvedata_res = results["twelvedata"]

            # 4. Last-Good Fallback
            last_cache = await get_market_snapshot()
            last_map = {i["ticker"]: i for i in last_cache.get("snapshot", [])}

            # 5. Build snapshot
            snapshot = []
            for asset in assets:
                ticker = asset.ticker.upper()
                data = None

                if asset.asset_type == AssetType.CRYPTO:
                    key = normalize_crypto_ticker(ticker)
                    data = binance_res["data"].get(key)
                elif asset.asset_type == AssetType.FOREX:
                    key = normalize_forex(ticker)
                    data = choose_best(
                        fcs_res["data"].get(key),
                        twelvedata_res["data"].get(key),
                    )
                elif asset.asset_type in {AssetType.STOCK, AssetType.ETF}:
                    data = choose_best(
                        polygon_res["data"].get(ticker),
                        eodhd_res["data"].get(ticker),
                        alpha_vantage_res["data"].get(ticker),
                    )
                    if not data:
                        data = choose_best(
                            finnhub_res["data"].get(ticker),
                            twelvedata_res["data"].get(ticker),
                        )

                # Fallback to last-good
                if not data:
                    data = last_map.get(ticker)

                if not data:
                    logger.warning(f"[SNAPSHOT] Missing data for: {ticker}")

                if data:
                    item_data = {
                        "id": str(asset.id),
                        "ticker": ticker,
                        "asset_type": asset.asset_type.value,
                        **data,
                    }
                    if asset.asset_type in {AssetType.STOCK, AssetType.ETF}:
                        item_data["market_closed"] = is_market_closed()
                    snapshot.append(item_data)

                    # Queue for batch DB write
                    ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                    price = float(data.get("price", 0))
                    if price > 0:
                        await db_buffer.add({
                            "asset_id": asset.id,
                            "timestamp": ts,
                            "open": price,
                            "high": price,
                            "low": price,
                            "close": price,
                            "volume": None,
                        })

            # 6. Telemetry
            coverage = len(snapshot) / len(assets) * 100 if assets else 0
            sources = Counter(i.get("source", "unknown") for i in snapshot)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"[SNAPSHOT] Coverage: {coverage:.1f}% | Sources: {dict(sources)} | {elapsed_ms:.0f}ms")

            # 7. Intelligence
            intelligence_map = await fetch_intelligence_map()
            snapshot = apply_intelligence(snapshot, intelligence_map)
            applied = sum(1 for i in snapshot if i.get("impact_score", 0) > 0)
            logger.info(f"[SNAPSHOT] Intelligence applied: {applied}")

            # 8. Staleness check
            _snapshot_version += 1
            now_iso = datetime.now(timezone.utc).isoformat()

            # Check if we should flag degraded mode
            degraded = coverage < 30  # less than 30% coverage = degraded
            
            payload = {
                "version": _snapshot_version,
                "as_of": now_iso,
                "snapshot": snapshot,
                "last_updated": now_iso,
                "degraded": degraded,
            }
            await set_market_snapshot(payload)

        except Exception as e:
            logger.error(f"Snapshot loop error: {e}")
            print(f"[SNAPSHOT LOOP CRASHED] {e}")

        # Fixed-interval scheduling (no drift)
        sleep_time = max(0, next_tick - time.time())
        await asyncio.sleep(sleep_time)