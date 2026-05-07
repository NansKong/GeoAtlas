from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.predictions.models import Prediction, PredictionOutcome
from modules.predictions.service import classify_prediction_outcome
from modules.market.models import MarketPrice
from workers.celery_app import celery_app


def _nearest_price(session: Session, asset_id, target_at):
    after = session.execute(
        select(MarketPrice.close)
        .where(MarketPrice.asset_id == asset_id, MarketPrice.timestamp >= target_at)
        .order_by(MarketPrice.timestamp.asc())
        .limit(1)
    ).scalar_one_or_none()
    if after is not None:
        return float(after)

    before = session.execute(
        select(MarketPrice.close)
        .where(MarketPrice.asset_id == asset_id, MarketPrice.timestamp <= target_at)
        .order_by(MarketPrice.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()
    if before is not None:
        return float(before)
    return None


@celery_app.task(name="workers.predictions.verify_event_outcome", bind=True, max_retries=2)
def verify_event_outcome(self, prediction_id: str):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    with Session(engine) as session:
        prediction = session.get(Prediction, uuid.UUID(prediction_id))
        if not prediction or prediction.resolve_at is None:
            return {"prediction_id": prediction_id, "status": "missing_or_unresolvable"}

        start_price = _nearest_price(session, prediction.asset_id, prediction.predicted_at)
        end_price = _nearest_price(session, prediction.asset_id, prediction.resolve_at)
        if start_price is None or end_price is None or start_price <= 0:
            return {"prediction_id": prediction_id, "status": "insufficient_market_data"}

        actual_change_pct = ((end_price - start_price) / start_price) * 100.0
        prediction.actual_change_pct = round(actual_change_pct, 4)
        prediction.outcome = classify_prediction_outcome(prediction.predicted_direction, actual_change_pct)
        prediction.resolved_at = datetime.now(timezone.utc)
        session.commit()

        return {
            "prediction_id": prediction_id,
            "status": "verified",
            "outcome": prediction.outcome.value,
            "actual_change_pct": prediction.actual_change_pct,
        }


@celery_app.task(name="workers.predictions.verify_due_predictions", bind=True, max_retries=2)
def verify_due_predictions(self, batch_size: int = 200):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    now = datetime.now(timezone.utc)
    queued = 0

    with Session(engine) as session:
        rows = session.execute(
            select(Prediction.id)
            .where(
                Prediction.outcome == PredictionOutcome.PENDING,
                Prediction.resolve_at.is_not(None),
                Prediction.resolve_at <= now,
            )
            .order_by(Prediction.resolve_at.asc())
            .limit(batch_size)
        ).scalars().all()

    for prediction_id in rows:
        verify_event_outcome.delay(str(prediction_id))
        queued += 1

    return {"queued": queued}

@celery_app.task(name="workers.predictions.generate_predictions_for_event", bind=True, max_retries=2, soft_time_limit=20, time_limit=30)
def generate_predictions_for_event(self, event_id: str):
    import redis
    import json
    import logging
    from workers.model_runtime import predict_regime_xgboost, predict_chronos_trajectory, predict_volatility_lstm
    from datetime import timedelta
    from sqlalchemy import text
    from collections import deque

    logger = logging.getLogger(__name__)
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    with Session(engine) as session:
        # 1. Get impacted assets
        impacted_assets = session.execute(
            text("SELECT asset_id, impact_strength FROM event_impacts WHERE event_id = :event_id"),
            {"event_id": event_id}
        ).fetchall()

        if not impacted_assets:
            return {"event_id": event_id, "predictions_created": 0}

        results = []
        now = datetime.now(timezone.utc)

        # 2. Redis pipeline (batch read)
        pipe = r.pipeline()
        asset_ids = [row.asset_id for row in impacted_assets]
        for asset_id in asset_ids:
            pipe.get(f"feature:asset:{asset_id}")
        redis_results = pipe.execute()

        for asset_id, data in zip(asset_ids, redis_results):
            if not data:
                continue

            try:
                payload = json.loads(data)
                features = payload["features"]
                ts_str = payload.get("ts")
            except (json.JSONDecodeError, KeyError):
                continue

            # Freshness Check
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str)
            if now - ts > timedelta(minutes=10):
                continue

            # 3. Validate features
            if "7d_vol" not in features or "sentiment_momentum" not in features:
                continue

            # 4. Fast XGBoost Regime Filter
            pred = predict_regime_xgboost(features)
            if not pred:
                continue

            p_breakout = float(pred.get("p_breakout", 0.5))
            confidence = float(pred["confidence"])
            sentiment_momentum = float(features.get("sentiment_momentum", 0.0))
            direction = 1 if sentiment_momentum > 0 else -1
            
            if p_breakout < 0.5 and confidence > 0.8:
                continue

            score = (0.6 * p_breakout + 0.4 * min(1.0, abs(sentiment_momentum)))
            vol = float(features.get("7d_vol", features.get("volatility_7d", 0.05)))
            expected_change_pct = direction * p_breakout * abs(vol) * min(1.0, abs(sentiment_momentum)) * 2.0

            results.append({
                "asset_id": asset_id,
                "features": features,
                "xgb_p_breakout": p_breakout,
                "xgb_change_pct": expected_change_pct,
                "xgb_confidence": score,
                "score": score,
            })

        # 5. Hard Limit Top-K Assets for heavy models
        TOP_K = 3
        MIN_CONF = 0.6
        filtered = [r for r in results if r["score"] >= MIN_CONF]
        if not filtered:
            filtered = results
        
        top_assets = sorted(filtered, key=lambda x: x["score"], reverse=True)[:TOP_K]

        # 6. Ensemble Expansion on Top-K
        import uuid
        event_uuid = uuid.UUID(event_id) if isinstance(event_id, str) else event_id
        persisted_predictions = 0
        
        for item in top_assets:
            asset_id = item["asset_id"]
            features = item["features"]
            
            # Sub-Model 1: VolatilityNet (LSTM)
            # Default fallback if LSTM missing
            lstm_confidence = 0.5
            try:
                # Need sequence input. Currently simulate single step or fallback.
                # Production code would assemble historical sequence here.
                lstm_pred = predict_volatility_lstm([features] * 10) 
                if lstm_pred and "confidence" in lstm_pred:
                    lstm_confidence = float(lstm_pred["confidence"])
            except Exception as e:
                logger.warning("VolatilityNet failed in ensemble pipeline", exc_info=e)
                lstm_confidence = item["xgb_confidence"] # fallback to base variance

            # Sub-Model 2: ChronosNet (T5)
            # Fetch historical close prices
            history_rows = session.execute(
                text("SELECT close FROM market_prices WHERE asset_id = :id ORDER BY timestamp DESC LIMIT 48"),
                {"id": asset_id}
            ).fetchall()
            
            chronos_pred_pct, chronos_confidence = 0.0, 0.0
            if history_rows and len(history_rows) >= 2:
                prices = [float(r.close) for r in reversed(history_rows)]
                current_price = prices[-1]
                try:
                    c_out = predict_chronos_trajectory(prices, horizon_steps=24)
                    if c_out and current_price > 0:
                        median_f = c_out["median_prediction"]
                        delta = (median_f - current_price) / current_price
                        # Threshold Buffer Logic
                        if delta > 0.002:
                            c_dir = 1.0
                        elif delta < -0.002:
                            c_dir = -1.0
                        else:
                            c_dir = 0.0
                            
                        chronos_pred_pct = delta * 100.0
                        # Confidence proxy: bounds tightness
                        high = c_out["predicted_quantiles"]["0.90"]
                        low = c_out["predicted_quantiles"]["0.10"]
                        spread = abs(high - low) / current_price 
                        chronos_confidence = max(0.0, 1.0 - spread)  # tighter spread = higher confidence
                except Exception as e:
                    logger.warning("ChronosNet failed in ensemble pipeline", exc_info=e)

            # 7. Final Meta-Ensemble Aggregation
            # Normalize outputs
            c_mag = float(chronos_pred_pct)
            x_mag = float(item["xgb_change_pct"])
            x_dir = 1.0 if x_mag > 0 else -1.0
            
            weights = {"xgb": 0.4, "lstm": 0.3, "chronos": 0.3}
            
            # Final magnitude voting combining direction and scale
            final_mag = (
                weights["xgb"] * x_mag + 
                weights["chronos"] * c_mag + 
                weights["lstm"] * (x_dir * lstm_confidence * item["xgb_p_breakout"] * 2.0)
            )
            
            final_confidence = (
                weights["xgb"] * item["xgb_confidence"] +
                weights["lstm"] * lstm_confidence +
                weights["chronos"] * chronos_confidence
            )

            # Avoid noise flipping
            if abs(final_mag) < 0.1:
                final_dir = "neutral"
            else:
                final_dir = "up" if final_mag > 0 else "down"

            # 8. Persist final ensembled state
            logger.info(json.dumps({
                "action": "ensemble_fusion_audit",
                "timestamp": now.isoformat(),
                "asset_id": str(asset_id),
                "model_version": "GeoAtlas-Ensemble-v1",
                "xgb_signal": {"mag": x_mag, "conf": item["xgb_confidence"]},
                "lstm_volatility": {"conf": lstm_confidence},
                "chronos_forecast": {"mag": c_mag, "conf": chronos_confidence},
                "final_prediction": {"mag": final_mag, "dir": final_dir, "conf": final_confidence}
            }))

            # Only record the final ensemble to database to avoid dupe records
            prediction = Prediction(
                id=uuid.uuid4(),
                event_id=event_uuid,
                asset_id=asset_id,
                predicted_at=now,
                predicted_direction=final_dir,
                predicted_change_pct=round(final_mag, 4),
                confidence_score=final_confidence,
                model_version="GeoAtlas-Ensemble-v1",
                resolve_at=now + timedelta(days=1),
                outcome=PredictionOutcome.PENDING
            )
            session.add(prediction)
            persisted_predictions += 1

        session.commit()

    return {"event_id": event_id, "predictions_created": persisted_predictions}

