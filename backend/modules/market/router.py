import json
from datetime import datetime, timezone
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.events.models import Event, EventImpact
from modules.market.models import Asset, AssetType, Watchlist
from modules.market.schemas import (
    AssetOut,
    FundamentalsOut,
    OHLCVOut,
    QuoteOut,
    WatchlistCreateIn,
    WatchlistItemOut,
    WatchlistLatestImpactOut,
)
from modules.market.service import (
    get_fundamentals,
    get_historical_1y,
    get_ohlcv,
    get_quote,
    market_stream_manager,
)
from modules.users.models import User
from modules.users.router import get_current_user

router = APIRouter(tags=["Market"])


def _parse_asset_type(token: str) -> AssetType:
    normalized = token.strip().replace("-", "_").replace(" ", "_").upper()
    try:
        return AssetType[normalized]
    except KeyError as exc:
        valid = ", ".join(t.value for t in AssetType)
        raise HTTPException(status_code=422, detail=f"Invalid asset_type '{token}'. Use one of: {valid}") from exc


def _parse_tickers(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    return [token.strip().upper() for token in parts if token and token.strip()]


def _asset_out(asset: Asset) -> AssetOut:
    return AssetOut(
        id=asset.id,
        ticker=asset.ticker,
        name=asset.name,
        asset_type=asset.asset_type.value,
        sector=asset.sector,
        industry=asset.industry,
        country=asset.country,
        exchange=asset.exchange,
        currency=asset.currency,
    )


async def _resolve_asset(
    db: AsyncSession,
    *,
    asset_id: Optional[uuid.UUID],
    ticker: Optional[str],
) -> Asset:
    if asset_id is not None:
        asset = await db.get(Asset, asset_id)
        if asset:
            return asset
        raise HTTPException(status_code=404, detail="Asset not found")
    if ticker:
        result = await db.execute(select(Asset).where(Asset.ticker == ticker.strip().upper()))
        asset = result.scalar_one_or_none()
        if asset:
            return asset
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found")
    raise HTTPException(status_code=422, detail="Either asset_id or ticker is required")


async def _latest_watchlist_impact(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> Optional[WatchlistLatestImpactOut]:
    result = await db.execute(
        select(EventImpact, Event)
        .join(Event, Event.id == EventImpact.event_id)
        .where(EventImpact.asset_id == asset_id)
        .order_by(Event.published_at.desc(), EventImpact.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        return None
    impact, event = row
    return WatchlistLatestImpactOut(
        event_id=event.id,
        event_title=event.title,
        event_type=event.event_type.value,
        impact_direction=impact.impact_direction.value,
        impact_strength=impact.impact_strength,
        confidence_score=impact.confidence_score,
        published_at=event.published_at,
    )


from core.market_cache import get_market_snapshot

@router.get("/market/snapshot", tags=["Market (Hybrid Layer)"])
async def market_snapshot_endpoint():
    """
    Returns the batched, cached representation of all tracked assets.
    Near-zero latency since it returns the in-memory dictionary.
    """
    data = await get_market_snapshot()
    return data

@router.get("/assets", response_model=List[AssetOut])
async def list_assets(
    asset_type: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(Asset).order_by(Asset.ticker).limit(limit)
    if asset_type:
        query = query.where(Asset.asset_type == _parse_asset_type(asset_type))
    if sector:
        query = query.where(Asset.sector.ilike(f"%{sector}%"))

    result = await db.execute(query)
    assets = result.scalars().all()
    return [
        AssetOut(
            id=a.id,
            ticker=a.ticker,
            name=a.name,
            asset_type=a.asset_type.value,
            sector=a.sector,
            industry=a.industry,
            country=a.country,
            exchange=a.exchange,
            currency=a.currency,
        )
        for a in assets
    ]


@router.get("/assets/{ticker}", response_model=AssetOut)
async def get_asset(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Asset).where(Asset.ticker == ticker.upper()))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found")
    return _asset_out(asset)


@router.get("/watchlists", response_model=List[WatchlistItemOut])
async def list_watchlists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Watchlist, Asset)
        .join(Asset, Asset.id == Watchlist.asset_id)
        .where(Watchlist.user_id == current_user.id)
        .order_by(Watchlist.created_at.desc())
    )
    rows = result.all()
    items: list[WatchlistItemOut] = []
    for watchlist, asset in rows:
        items.append(
            WatchlistItemOut(
                id=watchlist.id,
                user_id=watchlist.user_id,
                asset_id=watchlist.asset_id,
                created_at=watchlist.created_at,
                asset=_asset_out(asset),
                latest_impact=await _latest_watchlist_impact(db, watchlist.asset_id),
            )
        )
    return items


@router.post("/watchlists", response_model=WatchlistItemOut, status_code=201)
async def create_watchlist(
    payload: WatchlistCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = await _resolve_asset(db, asset_id=payload.asset_id, ticker=payload.ticker)
    existing = await db.execute(
        select(Watchlist).where(Watchlist.user_id == current_user.id, Watchlist.asset_id == asset.id)
    )
    watchlist = existing.scalar_one_or_none()
    if watchlist is None:
        watchlist = Watchlist(user_id=current_user.id, asset_id=asset.id)
        db.add(watchlist)
        await db.flush()
        await db.refresh(watchlist)

    return WatchlistItemOut(
        id=watchlist.id,
        user_id=watchlist.user_id,
        asset_id=watchlist.asset_id,
        created_at=watchlist.created_at,
        asset=_asset_out(asset),
        latest_impact=await _latest_watchlist_impact(db, watchlist.asset_id),
    )


@router.delete("/watchlists/{watchlist_id}", status_code=204)
async def delete_watchlist(
    watchlist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id)
    )
    watchlist = result.scalar_one_or_none()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    await db.delete(watchlist)


@router.get("/market/quote/{ticker}", response_model=QuoteOut)
async def quote_endpoint(
    ticker: str,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await get_quote(db, ticker=ticker, refresh=refresh)


@router.get("/market/ohlcv/{ticker}", response_model=OHLCVOut)
async def ohlcv_endpoint(
    ticker: str,
    interval: str = Query("1day"),
    limit: int = Query(120, ge=1, le=365),
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await get_ohlcv(db, ticker=ticker, interval=interval, limit=limit, refresh=refresh)


@router.get("/market/historical/{ticker}", response_model=OHLCVOut)
async def historical_1y_endpoint(
    ticker: str,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await get_historical_1y(db, ticker=ticker, refresh=refresh)


@router.get("/market/fundamentals/{ticker}", response_model=FundamentalsOut)
async def fundamentals_endpoint(
    ticker: str,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await get_fundamentals(db, ticker=ticker, refresh=refresh)


@router.websocket("/market/ws")
async def market_ws_endpoint(websocket: WebSocket):
    await market_stream_manager.connect(websocket)

    initial_tickers = _parse_tickers(websocket.query_params.get("tickers"))
    if initial_tickers:
        subscribed = await market_stream_manager.replace_subscriptions(websocket, initial_tickers)
    else:
        subscribed = await market_stream_manager.get_subscriptions(websocket)

    await websocket.send_json(
        {
            "type": "connected",
            "provider": market_stream_manager.provider,
            "subscribed": subscribed,
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON payload"})
                continue

            action = str(payload.get("action", "")).strip().lower()
            tickers = _parse_tickers(payload.get("tickers"))

            if action in {"subscribe", "add"}:
                subscribed = await market_stream_manager.add_subscriptions(websocket, tickers)
                await websocket.send_json({"type": "subscribed", "tickers": subscribed})
            elif action in {"unsubscribe", "remove"}:
                subscribed = await market_stream_manager.remove_subscriptions(websocket, tickers)
                await websocket.send_json({"type": "subscribed", "tickers": subscribed})
            elif action in {"set", "replace"}:
                subscribed = await market_stream_manager.replace_subscriptions(websocket, tickers)
                await websocket.send_json({"type": "subscribed", "tickers": subscribed})
            elif action == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "Unknown action. Use subscribe/unsubscribe/set/ping.",
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        await market_stream_manager.disconnect(websocket)
