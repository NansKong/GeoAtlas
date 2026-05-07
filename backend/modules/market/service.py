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
from sqlalchemy import select
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


async def _get_asset_or_404(db: AsyncSession, ticker: str) -> Asset:
    result = await db.execute(select(Asset).where(Asset.ticker == ticker.upper()))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found")
    return asset


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
        return {
            "price": float(price),
            "as_of": datetime.now(timezone.utc),
            "source": "alphavantage",
        }
    except Exception as exc:
        logger.warning("AlphaVantage quote failed for %s: %s", ticker, exc)
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
    quote: Optional[dict] = None

    if asset.asset_type in {AssetType.STOCK, AssetType.ETF, AssetType.INDEX}:
        quote = await _quote_from_polygon(ticker_upper)
        if quote is None:
            quote = await _quote_from_eodhd(ticker_upper)
        if quote is None:
            quote = await _quote_from_alpha_vantage(ticker_upper)
        if quote is None:
            quote = await _quote_from_finnhub(ticker_upper)
        if quote is None:
            quote = await _quote_from_twelve_data(ticker_upper, asset.asset_type)
    elif asset.asset_type == AssetType.FOREX:
        quote = await _quote_from_fcsapi(ticker_upper)
        if quote is None:
            quote = await _quote_from_twelve_data(ticker_upper, asset.asset_type)
    elif asset.asset_type == AssetType.CRYPTO:
        quote = await _quote_from_binance(ticker_upper)
        if quote is None:
            quote = await _quote_from_twelve_data(ticker_upper, asset.asset_type)
    elif asset.asset_type == AssetType.COMMODITY:
        quote = await _quote_from_twelve_data(ticker_upper, asset.asset_type)

    if quote is not None:
        await _persist_quote(db, asset.id, quote)

    if quote is None and _require_live_api():
        raise HTTPException(
            status_code=503,
            detail=f"Live quote provider unavailable for '{ticker_upper}'",
        )

    if quote is None:
        quote = await _quote_from_db(db, asset.id)

    if quote is None:
        raise HTTPException(status_code=404, detail=f"No quote data available for '{ticker_upper}'")

    cache_payload = {
        "price": quote["price"],
        "currency": asset.currency,
        "as_of": _to_iso(quote["as_of"]),
        "source": quote["source"],
    }
    await _cache_set_json(key, cache_payload, ttl_seconds=REALTIME_PRICE_TTL_SECONDS)

    return QuoteOut(
        ticker=ticker_upper,
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
    points: list[OHLCVPointOut] = []
    source = "db"

    if asset.asset_type in {AssetType.STOCK, AssetType.ETF, AssetType.INDEX}:
        eodhd_points = await _ohlcv_from_eodhd(ticker_upper, limit=limit)
        if eodhd_points:
            points = eodhd_points
            source = "eodhd"
        else:
            av_points = await _ohlcv_from_alpha_vantage(ticker_upper, limit=limit)
            if av_points:
                points = av_points
                source = "alphavantage"
            else:
                finnhub_points = await _ohlcv_from_finnhub(ticker_upper, limit=limit)
                if finnhub_points:
                    points = finnhub_points
                    source = "finnhub"
                else:
                    twelve_points = await _ohlcv_from_twelve_data(
                        ticker_upper,
                        limit=limit,
                        asset_type=asset.asset_type,
                    )
                    if twelve_points:
                        points = twelve_points
                        source = "twelve_data"
    elif asset.asset_type == AssetType.FOREX:
        fcs_points = await _ohlcv_from_fcsapi(ticker_upper, limit=limit)
        if fcs_points:
            points = fcs_points
            source = "fcsapi"
        else:
            twelve_points = await _ohlcv_from_twelve_data(
                ticker_upper,
                limit=limit,
                asset_type=asset.asset_type,
            )
            if twelve_points:
                points = twelve_points
                source = "twelve_data"
    elif asset.asset_type == AssetType.CRYPTO:
        binance_points = await _ohlcv_from_binance(ticker_upper, limit=limit)
        if binance_points:
            points = binance_points
            source = "binance"
        else:
            twelve_points = await _ohlcv_from_twelve_data(
                ticker_upper,
                limit=limit,
                asset_type=asset.asset_type,
            )
            if twelve_points:
                points = twelve_points
                source = "twelve_data"
    elif asset.asset_type == AssetType.COMMODITY:
        twelve_points = await _ohlcv_from_twelve_data(
            ticker_upper,
            limit=limit,
            asset_type=asset.asset_type,
        )
        if twelve_points:
            points = twelve_points
            source = "twelve_data"

    if points and source in {"eodhd", "fcsapi", "finnhub", "twelve_data", "alphavantage", "binance"}:
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
