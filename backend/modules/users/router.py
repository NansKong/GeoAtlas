from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.redis import get_redis
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from modules.events.models import Event, EventImpact, EventStatus, EventTag, EventType
from modules.events.schemas import AffectedAssetOut, EventListOut
from modules.market.models import Asset
from modules.users.models import InstitutionalApiKey, User
from modules.users.schemas import (
    AlertPreferencesOut,
    AlertPreferencesUpdate,
    ApiKeyCreateIn,
    ApiKeyCreateOut,
    ApiKeyOut,
    BillingCheckoutRequest,
    BillingLimitsOut,
    BillingPlanOut,
    BillingSessionOut,
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserOut,
    UserRegister,
)
from modules.users.service import (
    FREE_BOARD_LIMIT,
    FREE_PREDICTIONS_PER_DAY,
    build_prediction_quota_key,
    count_user_alerts,
    count_user_boards,
    create_institutional_api_key,
    is_institutional_or_admin,
    normalize_subscription_plan,
    prediction_quota_state,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
users_router = APIRouter(prefix="/users", tags=["Users"])
billing_router = APIRouter(prefix="/billing", tags=["Billing"])
institutional_router = APIRouter(prefix="/institutional", tags=["Institutional API"])

bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)

PUBLISHED_EVENT_STATUSES = (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)


def _base_alert_preferences(user: User) -> AlertPreferencesOut:
    raw = user.alert_preferences or {}
    tokens = [str(token).strip() for token in raw.get("web_push_tokens", []) if str(token).strip()]
    return AlertPreferencesOut(
        email_enabled=bool(raw.get("email_enabled", True)),
        web_push_enabled=bool(raw.get("web_push_enabled", False)),
        web_push_tokens=tokens,
        email_delivery_ready=bool(settings.SENDGRID_API_KEY),
        web_push_delivery_ready=bool(settings.FCM_SERVER_KEY),
    )


async def _stripe_request(method: str, path: str, data: dict[str, str] | None = None) -> dict:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    async with httpx.AsyncClient(
        base_url="https://api.stripe.com/v1",
        timeout=20,
        headers={"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"},
    ) as client:
        response = await client.request(method, path, data=data)
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"Stripe request failed: {detail}")
    return response.json()


async def _ensure_stripe_customer(db: AsyncSession, user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    payload = await _stripe_request(
        "POST",
        "/customers",
        data={
            "email": user.email,
            "name": user.username,
            "metadata[user_id]": str(user.id),
        },
    )
    customer_id = payload["id"]
    user.stripe_customer_id = customer_id
    await db.flush()
    return customer_id


def _stripe_plan_catalog() -> list[BillingPlanOut]:
    return [
        BillingPlanOut(
            id="free",
            name="Free",
            price_monthly=0,
            features=[
                "Live event feed",
                "5 published predictions per day",
                f"{FREE_BOARD_LIMIT} boards",
            ],
        ),
        BillingPlanOut(
            id="pro",
            name="Pro",
            price_monthly=19,
            features=[
                "Full published predictions",
                "Unlimited boards",
                "Alerts",
                "Billing portal access",
            ],
        ),
        BillingPlanOut(
            id="institutional",
            name="Institutional",
            price_monthly=299,
            features=[
                "All Pro features",
                "API key access",
                "Rate-limited event API",
                "Bulk internal integrations",
            ],
        ),
    ]


def _plan_from_price_id(price_id: str | None) -> str:
    if price_id and price_id == settings.STRIPE_PRICE_INSTITUTIONAL_MONTHLY:
        return "institutional"
    if price_id and price_id == settings.STRIPE_PRICE_PRO_MONTHLY:
        return "pro"
    return "free"


async def _apply_subscription_state(
    db: AsyncSession,
    *,
    customer_id: str | None,
    subscription_id: str | None,
    plan: str,
) -> None:
    if not customer_id and not subscription_id:
        return
    conditions = []
    if customer_id:
        conditions.append(User.stripe_customer_id == customer_id)
    if subscription_id:
        conditions.append(User.stripe_subscription_id == subscription_id)
    result = await db.execute(select(User).where(or_(*conditions)))
    user = result.scalar_one_or_none()
    if not user:
        return
    user.subscription_plan = normalize_subscription_plan(plan)
    if customer_id:
        user.stripe_customer_id = customer_id
    user.stripe_subscription_id = subscription_id
    await db.flush()


def _verify_stripe_signature(payload: bytes, signature_header: str | None) -> None:
    if not settings.STRIPE_WEBHOOK_SECRET:
        return
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    components = {}
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        components.setdefault(key, []).append(value)
    timestamp = (components.get("t") or [None])[0]
    provided = (components.get("v1") or [None])[0]
    if not timestamp or not provided:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature header")
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=400, detail="Stripe signature verification failed")


def _api_key_out(api_key: InstitutionalApiKey) -> ApiKeyOut:
    return ApiKeyOut.model_validate(api_key)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    result = await db.execute(select(User).where(User.username == payload.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        username=payload.username,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    return TokenPair(
        access_token=create_access_token(str(user.id), {"role": user.role}),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest):
    token_data = decode_token(payload.refresh_token, token_type="refresh")
    user_id = token_data["sub"]
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials, token_type="access")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive or invalid user")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, token_type="access")
        user_id = payload.get("sub")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
    except Exception:
        return None
    return None


@users_router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@users_router.get("/me/preferences", response_model=AlertPreferencesOut)
async def get_my_preferences(current_user: User = Depends(get_current_user)):
    return _base_alert_preferences(current_user)


@users_router.patch("/me/preferences", response_model=AlertPreferencesOut)
async def update_my_preferences(
    payload: AlertPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = _base_alert_preferences(current_user).model_dump()
    if payload.email_enabled is not None:
        base["email_enabled"] = payload.email_enabled
    if payload.web_push_enabled is not None:
        base["web_push_enabled"] = payload.web_push_enabled
    if payload.web_push_tokens is not None:
        base["web_push_tokens"] = [token.strip() for token in payload.web_push_tokens if token.strip()]
    current_user.alert_preferences = {
        "email_enabled": base["email_enabled"],
        "web_push_enabled": base["web_push_enabled"],
        "web_push_tokens": base["web_push_tokens"],
    }
    await db.flush()
    return _base_alert_preferences(current_user)


@billing_router.get("/plans", response_model=list[BillingPlanOut])
async def list_billing_plans():
    return _stripe_plan_catalog()


@billing_router.get("/limits", response_model=BillingLimitsOut)
async def billing_limits(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    day_token = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    quota_key = build_prediction_quota_key(
        user=current_user,
        client_host=request.client.host if request.client else None,
        day_token=day_token,
    )
    _, remaining = await prediction_quota_state(quota_key)
    if current_user is None:
        return BillingLimitsOut(
            subscription_plan="free",
            boards_used=0,
            boards_limit=FREE_BOARD_LIMIT,
            alerts_used=0,
            alerts_limit=0,
            predictions_remaining_today=remaining,
            predictions_daily_limit=FREE_PREDICTIONS_PER_DAY,
            stripe_configured=bool(settings.STRIPE_SECRET_KEY),
            institutional_api_enabled=bool(settings.STRIPE_PRICE_INSTITUTIONAL_MONTHLY),
        )

    plan = normalize_subscription_plan(current_user.subscription_plan)
    board_count, alert_count = await count_user_boards(db, current_user.id), await count_user_alerts(db, current_user.id)
    return BillingLimitsOut(
        subscription_plan=plan,
        boards_used=board_count,
        boards_limit=None if plan != "free" else FREE_BOARD_LIMIT,
        alerts_used=alert_count,
        alerts_limit=None if plan != "free" else 0,
        predictions_remaining_today=None if plan != "free" else remaining,
        predictions_daily_limit=None if plan != "free" else FREE_PREDICTIONS_PER_DAY,
        stripe_configured=bool(settings.STRIPE_SECRET_KEY),
        institutional_api_enabled=bool(settings.STRIPE_PRICE_INSTITUTIONAL_MONTHLY),
    )


@billing_router.post("/checkout-session", response_model=BillingSessionOut)
async def create_checkout_session(
    payload: BillingCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_id = await _ensure_stripe_customer(db, current_user)
    price_id = (
        settings.STRIPE_PRICE_INSTITUTIONAL_MONTHLY
        if payload.plan == "institutional"
        else settings.STRIPE_PRICE_PRO_MONTHLY
    )
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price for {payload.plan} is not configured")

    session = await _stripe_request(
        "POST",
        "/checkout/sessions",
        data={
            "mode": "subscription",
            "customer": customer_id,
            "success_url": settings.STRIPE_SUCCESS_URL,
            "cancel_url": settings.STRIPE_CANCEL_URL,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "metadata[user_id]": str(current_user.id),
            "metadata[plan]": payload.plan,
            "subscription_data[metadata][user_id]": str(current_user.id),
            "subscription_data[metadata][plan]": payload.plan,
            "allow_promotion_codes": "true",
        },
    )
    return BillingSessionOut(url=session["url"])


@billing_router.post("/portal-session", response_model=BillingSessionOut)
async def create_portal_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_id = await _ensure_stripe_customer(db, current_user)
    session = await _stripe_request(
        "POST",
        "/billing_portal/sessions",
        data={
            "customer": customer_id,
            "return_url": settings.STRIPE_PORTAL_RETURN_URL,
        },
    )
    return BillingSessionOut(url=session["url"])


@billing_router.post("/stripe/webhook", status_code=200)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    _verify_stripe_signature(payload, request.headers.get("Stripe-Signature"))
    event = json.loads(payload.decode("utf-8"))
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data.get("metadata", {}) or {}
        await _apply_subscription_state(
            db,
            customer_id=data.get("customer"),
            subscription_id=data.get("subscription"),
            plan=metadata.get("plan", "pro"),
        )
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        items = (((data.get("items") or {}).get("data")) or [])
        price_id = None
        if items:
            price_id = (((items[0] or {}).get("price")) or {}).get("id")
        metadata = data.get("metadata", {}) or {}
        plan = metadata.get("plan") or _plan_from_price_id(price_id)
        await _apply_subscription_state(
            db,
            customer_id=data.get("customer"),
            subscription_id=data.get("id"),
            plan=plan,
        )
    elif event_type == "customer.subscription.deleted":
        await _apply_subscription_state(
            db,
            customer_id=data.get("customer"),
            subscription_id=None,
            plan="free",
        )

    return {"received": True}


@billing_router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_institutional_or_admin(current_user):
        raise HTTPException(status_code=403, detail="Institutional plan required")
    result = await db.execute(
        select(InstitutionalApiKey)
        .where(
            InstitutionalApiKey.user_id == current_user.id,
            InstitutionalApiKey.revoked_at.is_(None),
        )
        .order_by(InstitutionalApiKey.created_at.desc())
    )
    return [_api_key_out(item) for item in result.scalars().all()]


@billing_router.post("/api-keys", response_model=ApiKeyCreateOut, status_code=201)
async def create_api_key(
    payload: ApiKeyCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key, raw_key = await create_institutional_api_key(db, current_user, payload.name)
    return ApiKeyCreateOut(
        **_api_key_out(api_key).model_dump(),
        api_key=raw_key,
    )


@billing_router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_institutional_or_admin(current_user):
        raise HTTPException(status_code=403, detail="Institutional plan required")
    result = await db.execute(
        select(InstitutionalApiKey).where(
            InstitutionalApiKey.id == key_id,
            InstitutionalApiKey.user_id == current_user.id,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.revoked_at = datetime.now(timezone.utc)
    await db.flush()


async def get_institutional_api_user(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    hashed = InstitutionalApiKey.hash_key(x_api_key.strip())
    result = await db.execute(
        select(InstitutionalApiKey, User)
        .join(User, User.id == InstitutionalApiKey.user_id)
        .where(
            InstitutionalApiKey.key_hash == hashed,
            InstitutionalApiKey.revoked_at.is_(None),
            User.is_active.is_(True),
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    api_key, user = row
    if not is_institutional_or_admin(user):
        raise HTTPException(status_code=403, detail="Institutional subscription required")

    redis = get_redis()
    minute_key = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    rate_key = f"institutional:rate:{api_key.id}:{minute_key}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 90)
    if count > settings.INSTITUTIONAL_API_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Institutional API rate limit exceeded")

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return user


@institutional_router.get("/events", response_model=list[EventListOut])
async def institutional_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_institutional_api_user),
):
    _ = current_user
    query = (
        select(Event)
        .where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
        .order_by(Event.published_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_type:
        normalized = event_type.strip().lower().replace("-", "_").replace(" ", "_")
        try:
            query = query.where(Event.event_type == EventType(normalized))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid event_type") from exc
    if country:
        query = query.where(Event.country.ilike(f"%{country.strip()}%"))

    result = await db.execute(query)
    events = result.scalars().all()
    items: list[EventListOut] = []
    for event in events:
        impact_count = await db.execute(select(func.count()).where(EventImpact.event_id == event.id))
        impact_assets = await db.execute(
            select(EventImpact, Asset)
            .join(Asset, Asset.id == EventImpact.asset_id)
            .where(EventImpact.event_id == event.id)
            .order_by(EventImpact.confidence_score.desc())
            .limit(5)
        )
        tags_result = await db.execute(
            select(EventTag.tag)
            .where(EventTag.event_id == event.id)
            .order_by(EventTag.tag.asc())
            .limit(8)
        )
        items.append(
            EventListOut(
                id=event.id,
                title=event.title,
                event_type=event.event_type.value,
                country=event.country,
                severity=event.severity,
                confidence_score=event.confidence_score,
                published_at=event.published_at,
                impact_count=int(impact_count.scalar() or 0),
                affected_assets=[
                    AffectedAssetOut(
                        ticker=asset.ticker,
                        name=asset.name,
                        impact_direction=impact.impact_direction.value,
                        impact_strength=impact.impact_strength,
                        confidence_score=impact.confidence_score,
                    )
                    for impact, asset in impact_assets.all()
                ],
                tags=list(tags_result.scalars().all()),
            )
        )
    return items
