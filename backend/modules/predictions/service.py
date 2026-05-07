from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.events.models import Event
from modules.market.models import Asset, MarketPrice
from modules.predictions.models import (
    Prediction,
    PredictionDirection,
    PredictionHorizon,
    PredictionOutcome,
)
from modules.predictions.schemas import PredictionCreateIn, PredictionOut, PredictionSummaryOut, AccuracyMetricsOut

DISPLAY_ACCURACY_THRESHOLD = 0.60
AUTO_DISABLE_THRESHOLD = 0.50


def _normalize_direction(value: str) -> PredictionDirection:
    token = value.strip().lower()
    try:
        return PredictionDirection(token)
    except ValueError as exc:
        valid = ", ".join(direction.value for direction in PredictionDirection)
        raise HTTPException(status_code=422, detail=f"Invalid predicted_direction '{value}'. Use one of: {valid}") from exc


def _normalize_horizon(value: str) -> PredictionHorizon:
    token = value.strip().lower()
    try:
        return PredictionHorizon(token)
    except ValueError as exc:
        valid = ", ".join(horizon.value for horizon in PredictionHorizon)
        raise HTTPException(status_code=422, detail=f"Invalid prediction_horizon '{value}'. Use one of: {valid}") from exc


def _resolve_at_from_horizon(predicted_at: datetime, horizon: PredictionHorizon) -> datetime:
    offsets = {
        PredictionHorizon.H1: timedelta(hours=1),
        PredictionHorizon.H6: timedelta(hours=6),
        PredictionHorizon.H24: timedelta(hours=24),
        PredictionHorizon.D7: timedelta(days=7),
        PredictionHorizon.D30: timedelta(days=30),
    }
    return predicted_at + offsets[horizon]


def _score_accuracy_case():
    return case(
        (Prediction.outcome == PredictionOutcome.CORRECT, 1.0),
        (Prediction.outcome == PredictionOutcome.PARTIAL, 0.5),
        (Prediction.outcome == PredictionOutcome.WRONG, 0.0),
        else_=None,
    )


async def _resolve_asset(db: AsyncSession, payload: PredictionCreateIn) -> Asset:
    if payload.asset_id:
        asset = await db.get(Asset, payload.asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return asset
    if payload.ticker:
        result = await db.execute(select(Asset).where(Asset.ticker == payload.ticker.upper()))
        asset = result.scalar_one_or_none()
        if asset:
            return asset
    raise HTTPException(status_code=422, detail="Either asset_id or ticker is required")


async def create_prediction(db: AsyncSession, payload: PredictionCreateIn) -> Prediction:
    event = await db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    asset = await _resolve_asset(db, payload)
    predicted_at = payload.predicted_at or datetime.now(timezone.utc)
    if predicted_at.tzinfo is None:
        predicted_at = predicted_at.replace(tzinfo=timezone.utc)

    horizon = _normalize_horizon(payload.prediction_horizon)
    resolve_at = payload.resolve_at or _resolve_at_from_horizon(predicted_at, horizon)
    if resolve_at.tzinfo is None:
        resolve_at = resolve_at.replace(tzinfo=timezone.utc)

    prediction = Prediction(
        event_id=event.id,
        asset_id=asset.id,
        predicted_direction=_normalize_direction(payload.predicted_direction),
        predicted_change_pct=payload.predicted_change_pct,
        prediction_horizon=horizon,
        confidence_score=payload.confidence_score,
        model_version=payload.model_version,
        predicted_at=predicted_at,
        resolve_at=resolve_at,
        outcome=PredictionOutcome.PENDING,
    )
    db.add(prediction)
    await db.flush()
    return prediction


async def compute_prediction_summary(db: AsyncSession) -> PredictionSummaryOut:
    accuracy_expr = _score_accuracy_case()
    counts = await db.execute(
        select(
            func.count(Prediction.id),
            func.count(case((Prediction.outcome != PredictionOutcome.PENDING, 1))),
            func.count(case((Prediction.outcome == PredictionOutcome.PENDING, 1))),
            func.avg(accuracy_expr),
        )
    )
    total, resolved, pending, overall_accuracy = counts.one()
    overall_value = float(overall_accuracy) if overall_accuracy is not None else None
    feature_enabled = overall_value is None or overall_value >= AUTO_DISABLE_THRESHOLD
    return PredictionSummaryOut(
        total_predictions=int(total or 0),
        resolved_predictions=int(resolved or 0),
        pending_predictions=int(pending or 0),
        overall_accuracy=overall_value,
        feature_enabled=feature_enabled,
    )


async def compute_accuracy_metrics(db: AsyncSession) -> AccuracyMetricsOut:
    where_resolved = Prediction.outcome != PredictionOutcome.PENDING
    
    rows = (await db.execute(
        select(Prediction, Event.event_type)
        .join(Event, Event.id == Prediction.event_id)
        .where(where_resolved)
    )).all()
    
    if not rows:
        return AccuracyMetricsOut()

    total_resolved = len(rows)
    
    total_score = 0.0
    dir_correct = 0
    abs_error_sum = 0.0
    
    tp, fp, fn, tn = 0, 0, 0, 0
    trade_returns = []

    model_acc = {}
    event_acc = {}
    horizon_acc = {}

    for pred, event_type_raw in rows:
        # Score calculation mapping from outcome
        score = 1.0 if pred.outcome == PredictionOutcome.CORRECT else (0.5 if pred.outcome == PredictionOutcome.PARTIAL else 0.0)
        total_score += score
        
        actual_change = float(pred.actual_change_pct) if pred.actual_change_pct is not None else 0.0
        pred_change = float(pred.predicted_change_pct) if pred.predicted_change_pct is not None else 0.0
        
        # Direction
        pred_dir_val = 1 if pred.predicted_direction.value == "up" else -1
        actual_dir_val = 1 if actual_change > 0 else (-1 if actual_change < 0 else 0)
        
        if pred_dir_val == actual_dir_val:
            dir_correct += 1
            
        # MAE
        abs_error_sum += abs(pred_change - actual_change)
        
        # Confusion matrix (UP=Positive, DOWN=Negative)
        if pred_dir_val == 1 and actual_dir_val >= 0:
            tp += 1
        elif pred_dir_val == 1 and actual_dir_val < 0:
            fp += 1
        elif pred_dir_val == -1 and actual_dir_val > 0:
            fn += 1
        else:
            tn += 1

        # Trading simulate return
        trade_returns.append(pred_dir_val * actual_change)
        
        # Groupings
        m_ver = pred.model_version
        e_type = event_type_raw.value if hasattr(event_type_raw, "value") else str(event_type_raw)
        h_val = pred.prediction_horizon.value

        for key, d in [(m_ver, model_acc), (e_type, event_acc), (h_val, horizon_acc)]:
            if key not in d:
                d[key] = {"total": 0, "score": 0.0}
            d[key]["total"] += 1
            d[key]["score"] += score

    # Aggregates
    overall_accuracy = total_score / total_resolved
    directional_accuracy = dir_correct / total_resolved
    mae = abs_error_sum / total_resolved
    
    # Sharpe-like (Avg Return / StdDev)
    sharpe_ratio = 0.0
    if trade_returns:
        import math
        avg_ret = sum(trade_returns) / len(trade_returns)
        variance = sum((r - avg_ret) ** 2 for r in trade_returns) / len(trade_returns)
        std_dev = math.sqrt(variance)
        if std_dev > 0.0001:
            sharpe_ratio = avg_ret / std_dev
        else:
            sharpe_ratio = avg_ret

    from modules.predictions.schemas import ConfusionMatrixOut
    return AccuracyMetricsOut(
        overall_accuracy=overall_accuracy,
        directional_accuracy=directional_accuracy,
        mae=mae,
        sharpe_ratio=sharpe_ratio,
        confusion_matrix=ConfusionMatrixOut(tp=tp, fp=fp, fn=fn, tn=tn),
        by_model_version={k: v["score"]/v["total"] for k, v in model_acc.items()},
        by_event_type={k: v["score"]/v["total"] for k, v in event_acc.items()},
        by_horizon={k: v["score"]/v["total"] for k, v in horizon_acc.items()},
        total_resolved=total_resolved,
    )



async def _accuracy_maps(
    db: AsyncSession,
    *,
    model_version: Optional[str] = None,
    horizon: Optional[PredictionHorizon] = None,
) -> tuple[dict[tuple[str, str], float], dict[str, float], Optional[float]]:
    accuracy_expr = _score_accuracy_case()
    where_clauses = [Prediction.outcome != PredictionOutcome.PENDING]
    if model_version:
        where_clauses.append(Prediction.model_version == model_version)
    if horizon:
        where_clauses.append(Prediction.prediction_horizon == horizon)

    grouped = await db.execute(
        select(
            Prediction.model_version,
            Prediction.prediction_horizon,
            func.avg(accuracy_expr),
        )
        .where(*where_clauses)
        .group_by(Prediction.model_version, Prediction.prediction_horizon)
    )
    by_model_horizon = {
        (str(row[0]), row[1].value if hasattr(row[1], "value") else str(row[1])): float(row[2])
        for row in grouped.all()
        if row[2] is not None
    }

    by_event_rows = await db.execute(
        select(
            Event.event_type,
            func.avg(accuracy_expr),
        )
        .join(Event, Event.id == Prediction.event_id)
        .where(*where_clauses)
        .group_by(Event.event_type)
    )
    by_event_type = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): float(row[1])
        for row in by_event_rows.all()
        if row[1] is not None
    }

    overall = await db.execute(select(func.avg(accuracy_expr)).where(*where_clauses))
    overall_accuracy = overall.scalar_one_or_none()
    return by_model_horizon, by_event_type, float(overall_accuracy) if overall_accuracy is not None else None


async def list_predictions(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    event_id: Optional[uuid.UUID] = None,
    ticker: Optional[str] = None,
    horizon: Optional[str] = None,
    history_only: bool = False,
    published_only: bool = True,
) -> list[PredictionOut]:
    horizon_enum = _normalize_horizon(horizon) if horizon else None
    accuracy_by_model_horizon, accuracy_by_event_type, overall_accuracy = await _accuracy_maps(
        db,
        horizon=horizon_enum,
    )
    feature_enabled = overall_accuracy is None or overall_accuracy >= AUTO_DISABLE_THRESHOLD

    query = (
        select(Prediction, Event.title, Event.event_type, Asset.ticker, Asset.name)
        .join(Event, Event.id == Prediction.event_id)
        .join(Asset, Asset.id == Prediction.asset_id)
        .order_by(Prediction.predicted_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_id:
        query = query.where(Prediction.event_id == event_id)
    if ticker:
        query = query.where(Asset.ticker == ticker.upper())
    if horizon_enum:
        query = query.where(Prediction.prediction_horizon == horizon_enum)
    if history_only:
        query = query.where(Prediction.outcome != PredictionOutcome.PENDING)

    rows = (await db.execute(query)).all()
    items: list[PredictionOut] = []
    for prediction, event_title, event_type, asset_ticker, asset_name in rows:
        model_accuracy = accuracy_by_model_horizon.get((prediction.model_version, prediction.prediction_horizon.value))
        event_type_key = event_type.value if hasattr(event_type, "value") else str(event_type)
        event_accuracy = accuracy_by_event_type.get(event_type_key)
        eligible = feature_enabled and event_accuracy is not None and event_accuracy >= DISPLAY_ACCURACY_THRESHOLD
        item = PredictionOut(
            id=prediction.id,
            event_id=prediction.event_id,
            asset_id=prediction.asset_id,
            event_title=event_title,
            event_type=event_type_key,
            ticker=asset_ticker,
            asset_name=asset_name,
            predicted_direction=prediction.predicted_direction.value,
            predicted_change_pct=prediction.predicted_change_pct,
            prediction_horizon=prediction.prediction_horizon.value,
            confidence_score=prediction.confidence_score,
            model_version=prediction.model_version,
            predicted_at=prediction.predicted_at,
            resolve_at=prediction.resolve_at,
            actual_change_pct=prediction.actual_change_pct,
            outcome=prediction.outcome.value,
            resolved_at=prediction.resolved_at,
            model_accuracy=model_accuracy,
            event_type_accuracy=event_accuracy,
            eligible_for_display=eligible,
            feature_enabled=feature_enabled,
        )
        if published_only and not history_only and not item.eligible_for_display:
            continue
        items.append(item)
    return items


async def _nearest_price_value(
    db: AsyncSession,
    *,
    asset_id,
    target_at: datetime,
) -> Optional[float]:
    after_stmt = (
        select(MarketPrice.close)
        .where(MarketPrice.asset_id == asset_id, MarketPrice.timestamp >= target_at)
        .order_by(MarketPrice.timestamp.asc())
        .limit(1)
    )
    after = (await db.execute(after_stmt)).scalar_one_or_none()
    if after is not None:
        return float(after)

    before_stmt = (
        select(MarketPrice.close)
        .where(MarketPrice.asset_id == asset_id, MarketPrice.timestamp <= target_at)
        .order_by(MarketPrice.timestamp.desc())
        .limit(1)
    )
    before = (await db.execute(before_stmt)).scalar_one_or_none()
    if before is not None:
        return float(before)
    return None


def classify_prediction_outcome(direction: PredictionDirection, actual_change_pct: float) -> PredictionOutcome:
    if direction == PredictionDirection.UP:
        if actual_change_pct >= 0.25:
            return PredictionOutcome.CORRECT
        if actual_change_pct <= -0.25:
            return PredictionOutcome.WRONG
        return PredictionOutcome.PARTIAL
    if direction == PredictionDirection.DOWN:
        if actual_change_pct <= -0.25:
            return PredictionOutcome.CORRECT
        if actual_change_pct >= 0.25:
            return PredictionOutcome.WRONG
        return PredictionOutcome.PARTIAL
    if abs(actual_change_pct) <= 1.0:
        return PredictionOutcome.CORRECT
    if abs(actual_change_pct) <= 2.0:
        return PredictionOutcome.PARTIAL
    return PredictionOutcome.WRONG


async def verify_prediction_outcome(db: AsyncSession, prediction_id: uuid.UUID) -> Optional[Prediction]:
    prediction = await db.get(Prediction, prediction_id)
    if not prediction:
        return None
    if prediction.resolve_at is None:
        return prediction

    start_price = await _nearest_price_value(db, asset_id=prediction.asset_id, target_at=prediction.predicted_at)
    end_price = await _nearest_price_value(db, asset_id=prediction.asset_id, target_at=prediction.resolve_at)
    if start_price is None or end_price is None or start_price <= 0:
        return prediction

    actual_change_pct = ((end_price - start_price) / start_price) * 100.0
    prediction.actual_change_pct = round(actual_change_pct, 4)
    prediction.outcome = classify_prediction_outcome(prediction.predicted_direction, actual_change_pct)
    prediction.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return prediction
