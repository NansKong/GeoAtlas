import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.users.models import User
from modules.users.router import get_current_user_optional
from modules.users.service import (
    FREE_PREDICTIONS_PER_DAY,
    build_prediction_quota_key,
    normalize_subscription_plan,
    prediction_quota_state,
    consume_prediction_quota,
)
from modules.predictions.schemas import PredictionCreateIn, PredictionOut, PredictionSummaryOut, AccuracyMetricsOut
from modules.predictions.service import compute_prediction_summary, create_prediction, list_predictions, compute_accuracy_metrics

router = APIRouter(tags=["Predictions"])


@router.get("/predictions", response_model=list[PredictionOut])
async def list_predictions_endpoint(
    event_id: Optional[uuid.UUID] = Query(None),
    ticker: Optional[str] = Query(None),
    horizon: Optional[str] = Query(None),
    history_only: bool = Query(False),
    published_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    *,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    response_limit = limit
    headers: dict[str, str] = {}
    plan = normalize_subscription_plan(current_user.subscription_plan) if current_user else "free"
    if published_only and plan == "free":
        day_token = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_key = build_prediction_quota_key(
            user=current_user,
            client_host=request.client.host if request and request.client else None,
            day_token=day_token,
        )
        _, remaining = await prediction_quota_state(quota_key)
        if remaining <= 0:
            raise HTTPException(
                status_code=403,
                detail=f"Free tier prediction limit reached for today ({FREE_PREDICTIONS_PER_DAY}/day).",
            )
        response_limit = min(limit, remaining)
        headers["X-GeoAtlas-Predictions-Limit"] = str(FREE_PREDICTIONS_PER_DAY)

    items = await list_predictions(
        db,
        limit=response_limit,
        offset=offset,
        event_id=event_id,
        ticker=ticker,
        horizon=horizon,
        history_only=history_only,
        published_only=published_only,
    )
    if published_only and plan == "free":
        day_token = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_key = build_prediction_quota_key(
            user=current_user,
            client_host=request.client.host if request and request.client else None,
            day_token=day_token,
        )
        _, remaining_after = await consume_prediction_quota(quota_key, len(items))
        headers["X-GeoAtlas-Predictions-Remaining"] = str(remaining_after)
        if response is not None:
            for key, value in headers.items():
                response.headers[key] = value
    return items


@router.post("/predictions", response_model=PredictionOut)
async def create_prediction_endpoint(
    payload: PredictionCreateIn,
    db: AsyncSession = Depends(get_db),
):
    prediction = await create_prediction(db, payload)
    rows = await list_predictions(db, event_id=prediction.event_id, limit=200, published_only=False)
    for item in rows:
        if item.id == prediction.id:
            return item
    raise RuntimeError("Created prediction could not be loaded")


@router.get("/predictions/summary", response_model=PredictionSummaryOut)
async def prediction_summary_endpoint(db: AsyncSession = Depends(get_db)):
    return await compute_prediction_summary(db)


@router.get("/predictions/accuracy", response_model=AccuracyMetricsOut)
async def prediction_accuracy_endpoint(db: AsyncSession = Depends(get_db)):
    """Provides precision and accuracy metrics grouped by model, event type, and horizon."""
    return await compute_accuracy_metrics(db)
