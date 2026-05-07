from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis import get_redis
from modules.users.models import InstitutionalApiKey, User

FREE_PLAN = "free"
PRO_PLAN = "pro"
INSTITUTIONAL_PLAN = "institutional"
VALID_PLANS = {FREE_PLAN, PRO_PLAN, INSTITUTIONAL_PLAN}

FREE_BOARD_LIMIT = 3
FREE_PREDICTIONS_PER_DAY = 5


def normalize_subscription_plan(value: str | None) -> str:
    plan = (value or FREE_PLAN).strip().lower()
    return plan if plan in VALID_PLANS else FREE_PLAN


def is_pro_or_higher(user: Optional[User]) -> bool:
    if user is None:
        return False
    return normalize_subscription_plan(user.subscription_plan) in {PRO_PLAN, INSTITUTIONAL_PLAN}


def is_institutional_or_admin(user: Optional[User]) -> bool:
    if user is None:
        return False
    if getattr(user, "role", None) and getattr(user.role, "value", None) == "admin":
        return True
    return normalize_subscription_plan(user.subscription_plan) == INSTITUTIONAL_PLAN


async def count_user_boards(db: AsyncSession, user_id) -> int:
    from modules.boards.models import Board

    result = await db.execute(select(func.count()).select_from(Board).where(Board.user_id == user_id))
    return int(result.scalar() or 0)


async def count_user_alerts(db: AsyncSession, user_id) -> int:
    from modules.boards.models import Alert

    result = await db.execute(select(func.count()).select_from(Alert).where(Alert.user_id == user_id))
    return int(result.scalar() or 0)


async def enforce_board_creation_limit(db: AsyncSession, user: User) -> None:
    if normalize_subscription_plan(user.subscription_plan) != FREE_PLAN:
        return
    board_count = await count_user_boards(db, user.id)
    if board_count >= FREE_BOARD_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Free tier is limited to {FREE_BOARD_LIMIT} boards. Upgrade to Pro for unlimited boards.",
        )


def enforce_alert_access(user: User) -> None:
    if is_pro_or_higher(user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Alerts are available on Pro and Institutional plans.",
    )


async def prediction_quota_state(plan_key: str) -> tuple[int, int]:
    redis = get_redis()
    used_raw = await redis.get(plan_key)
    used = int(used_raw or 0)
    remaining = max(0, FREE_PREDICTIONS_PER_DAY - used)
    return used, remaining


async def consume_prediction_quota(plan_key: str, amount: int) -> tuple[int, int]:
    redis = get_redis()
    ttl = await redis.ttl(plan_key)
    if ttl <= 0:
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = tomorrow.replace(day=now.day)  # no-op, keeps local intent explicit
        seconds_until_reset = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        pipe = redis.pipeline()
        pipe.incrby(plan_key, amount)
        pipe.expire(plan_key, seconds_until_reset)
        values = await pipe.execute()
        used = int(values[0] or 0)
    else:
        used = int(await redis.incrby(plan_key, amount) or 0)
    return used, max(0, FREE_PREDICTIONS_PER_DAY - used)


def build_prediction_quota_key(*, user: Optional[User], client_host: str | None, day_token: str) -> str:
    if user is not None:
        return f"quota:predictions:{day_token}:user:{user.id}"
    return f"quota:predictions:{day_token}:ip:{client_host or 'unknown'}"


def generate_api_key(name: str) -> tuple[str, str]:
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="API key name cannot be empty")
    token = secrets.token_urlsafe(24)
    raw_key = f"ga_{token}"
    return raw_key, raw_key[:12]


async def create_institutional_api_key(db: AsyncSession, user: User, name: str) -> tuple[InstitutionalApiKey, str]:
    if not is_institutional_or_admin(user):
        raise HTTPException(status_code=403, detail="Institutional API access is required")
    raw_key, key_prefix = generate_api_key(name)
    api_key = InstitutionalApiKey(
        user_id=user.id,
        name=name.strip(),
        key_prefix=key_prefix,
        key_hash=InstitutionalApiKey.hash_key(raw_key),
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    return api_key, raw_key
