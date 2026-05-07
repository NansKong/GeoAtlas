from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.boards.models import Alert, Board, BoardVisibility, Pin, PinContentType
from modules.boards.schemas import (
    AlertCreate,
    AlertOut,
    AlertUpdate,
    BoardCreate,
    BoardOut,
    BoardTemplateOut,
    BoardUpdate,
    PinCreate,
    PinOut,
    PinReorderIn,
    PinUpdate,
)
from modules.events.models import Event, EventStatus, EventType
from modules.market.models import Asset
from modules.users.models import User
from modules.users.router import get_current_user, get_current_user_optional
from modules.users.service import enforce_alert_access, enforce_board_creation_limit

router = APIRouter(prefix="/boards", tags=["Boards"])
pins_router = APIRouter(prefix="/pins", tags=["Pins"])
alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])

PUBLISHED_EVENT_STATUSES = (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)

BOARD_TEMPLATES = [
    {
        "slug": "china-us-tech-war",
        "title": "China-US Tech War",
        "description": "Semiconductor controls, retaliatory tariffs, export bans, and regulatory escalation.",
        "event_types": {EventType.TRADE_POLICY, EventType.SANCTION, EventType.REGULATION},
        "countries": {"China", "United States", "Taiwan", "Japan", "South Korea"},
        "keywords": ("chip", "semiconductor", "export", "tariff", "technology"),
    },
    {
        "slug": "middle-east-conflict",
        "title": "Middle East Conflict",
        "description": "Conflict developments, sanctions, and spillover market risk across the region.",
        "event_types": {EventType.CONFLICT, EventType.SANCTION, EventType.ENERGY_DISRUPTION},
        "countries": {"Israel", "Iran", "Lebanon", "Saudi Arabia", "Qatar", "United Arab Emirates"},
        "keywords": ("missile", "ceasefire", "gaza", "hezbollah", "iran"),
    },
    {
        "slug": "global-energy-crisis",
        "title": "Global Energy Crisis",
        "description": "Oil, gas, LNG, refinery, and shipping disruptions shaping commodity volatility.",
        "event_types": {EventType.ENERGY_DISRUPTION, EventType.TRADE_POLICY, EventType.REGULATION},
        "countries": {"Saudi Arabia", "Qatar", "United States", "Russia", "Iran"},
        "keywords": ("oil", "gas", "lng", "opec", "pipeline", "refinery"),
    },
]


def _touch_board(board: Board) -> None:
    board.updated_at = datetime.now(timezone.utc)


def _parse_visibility(raw: str) -> BoardVisibility:
    value = raw.strip().lower()
    if value == BoardVisibility.PUBLIC.value:
        return BoardVisibility.PUBLIC
    if value == BoardVisibility.PRIVATE.value:
        return BoardVisibility.PRIVATE
    raise HTTPException(status_code=422, detail="visibility must be 'public' or 'private'")


def _parse_pin_content_type(raw: str) -> PinContentType:
    value = raw.strip().lower()
    for item in PinContentType:
        if item.value == value:
            return item
    raise HTTPException(status_code=422, detail="content_type must be one of: event, asset, prediction, news")


def _parse_event_type(raw: str) -> str:
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    valid = {item.value for item in EventType}
    if value not in valid:
        raise HTTPException(status_code=422, detail=f"event_type must be one of: {', '.join(sorted(valid))}")
    return value


def _template_by_slug(slug: str) -> dict:
    for item in BOARD_TEMPLATES:
        if item["slug"] == slug:
            return item
    raise HTTPException(status_code=404, detail="Board template not found")


async def _resolve_asset(
    db: AsyncSession,
    *,
    asset_id: Optional[uuid.UUID],
    ticker: Optional[str],
) -> Optional[Asset]:
    if asset_id is not None:
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return asset
    if ticker:
        result = await db.execute(select(Asset).where(Asset.ticker == ticker.strip().upper()))
        asset = result.scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found")
        return asset
    return None


async def _pin_count(db: AsyncSession, board_id: uuid.UUID) -> int:
    result = await db.execute(select(func.count()).where(Pin.board_id == board_id))
    return int(result.scalar() or 0)


async def _board_out(db: AsyncSession, board: Board) -> BoardOut:
    return BoardOut(**board.__dict__, pin_count=await _pin_count(db, board.id))


async def _board_for_owner(db: AsyncSession, board_id: uuid.UUID, user_id: uuid.UUID) -> Board:
    result = await db.execute(select(Board).where(Board.id == board_id, Board.user_id == user_id))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


async def _next_pin_position(db: AsyncSession, board_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Pin.position), -1) + 1).where(Pin.board_id == board_id)
    )
    return int(result.scalar() or 0)


def _alert_out(alert: Alert, asset: Optional[Asset]) -> AlertOut:
    return AlertOut(
        id=alert.id,
        user_id=alert.user_id,
        asset_id=alert.asset_id,
        ticker=asset.ticker if asset else None,
        asset_name=asset.name if asset else None,
        event_type=alert.event_type,
        threshold=alert.threshold,
        is_active=alert.is_active,
        created_at=alert.created_at,
    )


@router.get("/templates", response_model=List[BoardTemplateOut])
async def list_board_templates():
    return [
        BoardTemplateOut(
            slug=item["slug"],
            title=item["title"],
            description=item["description"],
        )
        for item in BOARD_TEMPLATES
    ]


@router.post("/templates/{slug}", response_model=BoardOut, status_code=201)
async def create_board_from_template(
    slug: str,
    visibility: str = Query("private"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await enforce_board_creation_limit(db, current_user)
    template = _template_by_slug(slug)
    board = Board(
        user_id=current_user.id,
        title=template["title"],
        description=template["description"],
        visibility=_parse_visibility(visibility),
    )
    db.add(board)
    await db.flush()

    conditions = [Event.status.in_(PUBLISHED_EVENT_STATUSES), Event.event_type.in_(template["event_types"])]
    keyword_clauses = [Event.title.ilike(f"%{keyword}%") for keyword in template["keywords"]]
    keyword_clauses += [Event.description.ilike(f"%{keyword}%") for keyword in template["keywords"]]
    query = (
        select(Event)
        .where(
            *conditions,
            or_(
                Event.country.in_(template["countries"]),
                *keyword_clauses,
            ),
        )
        .order_by(Event.published_at.desc())
        .limit(6)
    )
    result = await db.execute(query)
    events = result.scalars().all()
    for index, event in enumerate(events):
        db.add(
            Pin(
                board_id=board.id,
                content_type=PinContentType.EVENT,
                content_id=event.id,
                note=f"Template seed from {template['title']}",
                position=index,
            )
        )
    _touch_board(board)
    await db.flush()
    await db.refresh(board)
    return await _board_out(db, board)


@router.post("", response_model=BoardOut, status_code=201)
async def create_board(
    payload: BoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await enforce_board_creation_limit(db, current_user)
    visibility = _parse_visibility(payload.visibility)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be empty")
    board = Board(
        user_id=current_user.id,
        title=title,
        description=payload.description,
        visibility=visibility,
        cover_image_url=payload.cover_image_url,
    )
    db.add(board)
    await db.flush()
    await db.refresh(board)
    return await _board_out(db, board)


@router.get("", response_model=List[BoardOut])
async def list_my_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Board).where(Board.user_id == current_user.id).order_by(Board.updated_at.desc())
    )
    return [await _board_out(db, board) for board in result.scalars().all()]


@router.get("/public", response_model=List[BoardOut])
async def list_public_boards(
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Board)
        .where(Board.visibility == BoardVisibility.PUBLIC)
        .order_by(Board.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [await _board_out(db, board) for board in result.scalars().all()]


@router.get("/{board_id}", response_model=BoardOut)
async def get_board(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    if board.visibility == BoardVisibility.PRIVATE and (current_user is None or board.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return await _board_out(db, board)


@router.patch("/{board_id}", response_model=BoardOut)
async def update_board(
    board_id: uuid.UUID,
    payload: BoardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    board = await _board_for_owner(db, board_id, current_user.id)

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        board.title = title
    if payload.description is not None:
        board.description = payload.description
    if payload.visibility is not None:
        board.visibility = _parse_visibility(payload.visibility)
    if payload.cover_image_url is not None:
        board.cover_image_url = payload.cover_image_url

    _touch_board(board)
    await db.flush()
    await db.refresh(board)
    return await _board_out(db, board)


@router.delete("/{board_id}", status_code=204)
async def delete_board(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    board = await _board_for_owner(db, board_id, current_user.id)
    await db.delete(board)


@router.post("/{board_id}/pins", response_model=PinOut, status_code=201)
async def add_pin(
    board_id: uuid.UUID,
    payload: PinCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    board = await _board_for_owner(db, board_id, current_user.id)
    pin = Pin(
        board_id=board_id,
        content_type=_parse_pin_content_type(payload.content_type),
        content_id=payload.content_id,
        note=payload.note,
        position=payload.position if payload.position is not None else await _next_pin_position(db, board_id),
    )
    db.add(pin)
    _touch_board(board)
    await db.flush()
    await db.refresh(pin)
    return pin


@router.patch("/{board_id}/pins/reorder", response_model=List[PinOut])
async def reorder_board_pins(
    board_id: uuid.UUID,
    payload: PinReorderIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    board = await _board_for_owner(db, board_id, current_user.id)
    result = await db.execute(
        select(Pin).where(Pin.board_id == board_id).order_by(Pin.position.asc(), Pin.created_at.asc())
    )
    pins = result.scalars().all()
    existing_ids = [pin.id for pin in pins]
    if set(existing_ids) != set(payload.pin_ids) or len(existing_ids) != len(payload.pin_ids):
        raise HTTPException(status_code=422, detail="pin_ids must include every board pin exactly once")
    index_map = {pin_id: position for position, pin_id in enumerate(payload.pin_ids)}
    for pin in pins:
        pin.position = index_map[pin.id]
    _touch_board(board)
    await db.flush()
    result = await db.execute(
        select(Pin).where(Pin.board_id == board_id).order_by(Pin.position.asc(), Pin.created_at.asc())
    )
    return result.scalars().all()


@router.get("/{board_id}/pins", response_model=List[PinOut])
async def list_pins(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    if board.visibility == BoardVisibility.PRIVATE and (current_user is None or board.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Pin).where(Pin.board_id == board_id).order_by(Pin.position.asc(), Pin.created_at.asc())
    )
    return result.scalars().all()


@router.delete("/{board_id}/pins/{pin_id}", status_code=204)
async def remove_pin(
    board_id: uuid.UUID,
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    board = await _board_for_owner(db, board_id, current_user.id)
    result = await db.execute(select(Pin).where(Pin.id == pin_id, Pin.board_id == board_id))
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    await db.delete(pin)
    _touch_board(board)


@pins_router.post("", response_model=PinOut, status_code=201)
async def create_pin(
    payload: PinCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.board_id is None:
        raise HTTPException(status_code=422, detail="board_id is required")
    board = await _board_for_owner(db, payload.board_id, current_user.id)
    pin = Pin(
        board_id=payload.board_id,
        content_type=_parse_pin_content_type(payload.content_type),
        content_id=payload.content_id,
        note=payload.note,
        position=payload.position if payload.position is not None else await _next_pin_position(db, payload.board_id),
    )
    db.add(pin)
    _touch_board(board)
    await db.flush()
    await db.refresh(pin)
    return pin


@pins_router.get("", response_model=List[PinOut])
async def list_pins_flat(
    board_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Pin)
        .join(Board, Board.id == Pin.board_id)
        .where(Board.user_id == current_user.id)
        .order_by(Pin.position.asc(), Pin.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if board_id:
        query = query.where(Pin.board_id == board_id)
    result = await db.execute(query)
    return result.scalars().all()


@pins_router.get("/{pin_id}", response_model=PinOut)
async def get_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pin)
        .join(Board, Board.id == Pin.board_id)
        .where(Pin.id == pin_id, Board.user_id == current_user.id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    return pin


@pins_router.patch("/{pin_id}", response_model=PinOut)
async def update_pin(
    pin_id: uuid.UUID,
    payload: PinUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pin, Board)
        .join(Board, Board.id == Pin.board_id)
        .where(Pin.id == pin_id, Board.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Pin not found")
    pin, board = row
    if payload.note is not None:
        pin.note = payload.note
    if payload.position is not None:
        pin.position = payload.position
    _touch_board(board)
    await db.flush()
    await db.refresh(pin)
    return pin


@pins_router.delete("/{pin_id}", status_code=204)
async def delete_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pin, Board)
        .join(Board, Board.id == Pin.board_id)
        .where(Pin.id == pin_id, Board.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Pin not found")
    pin, board = row
    await db.delete(pin)
    _touch_board(board)


@alerts_router.get("", response_model=List[AlertOut])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Alert, Asset)
        .outerjoin(Asset, Asset.id == Alert.asset_id)
        .where(Alert.user_id == current_user.id)
        .order_by(Alert.created_at.desc())
    )
    return [_alert_out(alert, asset) for alert, asset in result.all()]


@alerts_router.post("", response_model=AlertOut, status_code=201)
async def create_alert(
    payload: AlertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    enforce_alert_access(current_user)
    asset = await _resolve_asset(db, asset_id=payload.asset_id, ticker=payload.ticker)
    event_type = _parse_event_type(payload.event_type) if payload.event_type else None
    if asset is None and event_type is None:
        raise HTTPException(status_code=422, detail="Provide at least one of asset_id/ticker or event_type")

    alert = Alert(
        user_id=current_user.id,
        asset_id=asset.id if asset else None,
        event_type=event_type,
        threshold=payload.threshold,
        is_active=payload.is_active,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    return _alert_out(alert, asset)


@alerts_router.patch("/{alert_id}", response_model=AlertOut)
async def update_alert(
    alert_id: uuid.UUID,
    payload: AlertUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    asset = await _resolve_asset(db, asset_id=payload.asset_id, ticker=payload.ticker) if (
        payload.asset_id is not None or payload.ticker is not None
    ) else (await db.get(Asset, alert.asset_id) if alert.asset_id else None)

    if payload.asset_id is not None or payload.ticker is not None:
        alert.asset_id = asset.id if asset else None
    if payload.event_type is not None:
        alert.event_type = _parse_event_type(payload.event_type) if payload.event_type else None
    if payload.threshold is not None:
        alert.threshold = payload.threshold
    if payload.is_active is not None:
        alert.is_active = payload.is_active
    if alert.asset_id is None and alert.event_type is None:
        raise HTTPException(status_code=422, detail="Alert must include an asset or an event_type")

    await db.flush()
    await db.refresh(alert)
    return _alert_out(alert, asset)


@alerts_router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
