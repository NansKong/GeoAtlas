import os
import sys
import uuid
import asyncio
import logging
from datetime import datetime, timedelta, timezone

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.config import settings
from modules.events.models import Event, EventStatus, EventImpact
from modules.market.models import Asset, MarketPrice
from modules.predictions.models import Prediction, PredictionDirection, PredictionHorizon, PredictionOutcome
from workers.model_runtime import predict_sentiment, predict_chronos_trajectory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("generate_live_predictions")

IRRELEVANT_KEYWORDS = [
    "man city", "arsenal", "premier league", "chelsea", "manchester united", "liverpool fc",
    "real madrid", "barcelona", "champions league", "super bowl", "nba", "nfl", "mlb",
    "grand prix", "formula 1", "oscar", "grammy", "box office", "movie", "celebrity", "bar-b-que", "party"
]

def map_event_to_assets(text: str, event_type: str, asset_map: dict) -> list[Asset]:
    t_lower = text.lower()
    tickers = []
    
    if any(k in t_lower for k in ["oil", "hormuz", "petroleum", "energy", "opec", "pipeline", "gas"]):
        tickers = ["USO", "UNG", "XOM", "CVX"]
    elif any(k in t_lower for k in ["war", "conflict", "strike", "military", "ceasefire", "defense", "missile"]):
        tickers = ["XAUUSD", "LMT", "BTCUSDT", "USO"]
    elif any(k in t_lower for k in ["tariff", "trade", "sanction", "china", "export", "import"]):
        tickers = ["BABA", "EURUSD", "NVDA", "AAPL"]
    elif any(k in t_lower for k in ["fed", "inflation", "rate", "treasury", "cpi", "economy", "bank"]):
        tickers = ["TLT", "SPY", "EURUSD", "BTCUSDT"]
    else:
        tickers = ["SPY", "EURUSD", "BTCUSDT"]
        
    found = [asset_map[t] for t in tickers if t in asset_map]
    return found[:3] if found else list(asset_map.values())[:2]

async def generate_live_predictions_async():
    logger.info("Initializing Geopolitical & Macro Economic Prediction Generator...")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Clear previous predictions to refresh with intelligent asset mapping
        await session.execute(delete(Prediction))
        await session.commit()

        # Fetch published events
        events_query = (
            select(Event)
            .where(Event.status.in_((EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)))
            .order_by(Event.published_at.desc().nullslast(), Event.created_at.desc())
            .limit(60)
        )
        events_res = await session.execute(events_query)
        events = events_res.scalars().all()

        # Get available assets across types
        assets_res = await session.execute(
            select(Asset).order_by(Asset.created_at.asc()).limit(40)
        )
        assets = assets_res.scalars().all()

        if not assets:
            logger.error("No assets found in database!")
            return

        asset_map = {asset.ticker.upper(): asset for asset in assets}
        predictions_created = 0

        for event in events:
            event_text = f"{event.title or ''}. {event.description or ''}"
            
            # Filter out non-macro / non-financial headlines
            if any(kw in event_text.lower() for kw in IRRELEVANT_KEYWORDS):
                continue

            target_assets = map_event_to_assets(event_text, str(event.event_type), asset_map)
            
            # Run NLP sentiment analysis model
            nlp_sentiment = predict_sentiment(event_text)
            if nlp_sentiment is None:
                nlp_sentiment = -0.6 if any(k in event_text.lower() for k in ("war", "conflict", "sanction", "strike", "inflation")) else 0.4

            severity = float(event.severity or 3.0)
            confidence_base = float(event.confidence_score or 0.7)

            for asset in target_assets:
                # Fetch price history for Chronos model
                price_rows_res = await session.execute(
                    select(MarketPrice.close)
                    .where(MarketPrice.asset_id == asset.id)
                    .order_by(MarketPrice.timestamp.desc())
                    .limit(48)
                )
                price_rows = price_rows_res.scalars().all()

                price_history = [float(p) for p in reversed(price_rows)] if price_rows else [100.0 + i * 0.15 for i in range(24)]
                
                # ChronosNet time-series forecast
                chronos_change = 0.0
                try:
                    c_out = predict_chronos_trajectory(price_history, horizon_steps=24)
                    if c_out and len(price_history) > 0 and price_history[-1] > 0:
                        median_p = c_out.get("median_prediction", price_history[-1])
                        chronos_change = ((median_p - price_history[-1]) / price_history[-1]) * 100.0
                except Exception:
                    pass

                # Dynamic ML Fusion
                sent_impact = nlp_sentiment * (severity / 5.0) * 2.5
                combined_change = (0.55 * sent_impact) + (0.45 * chronos_change)
                combined_change = max(min(combined_change, 8.5), -8.5)

                if combined_change > 0.4:
                    direction_enum = PredictionDirection.UP
                    direction_str = "up"
                elif combined_change < -0.4:
                    direction_enum = PredictionDirection.DOWN
                    direction_str = "down"
                else:
                    direction_enum = PredictionDirection.NEUTRAL
                    direction_str = "neutral"

                final_confidence = min(0.95, max(0.55, confidence_base * 0.9))
                now = datetime.now(timezone.utc)
                resolve_time = now + timedelta(days=1)

                prediction = Prediction(
                    id=uuid.uuid4(),
                    event_id=event.id,
                    asset_id=asset.id,
                    predicted_direction=direction_enum,
                    predicted_change_pct=round(combined_change, 2),
                    prediction_horizon=PredictionHorizon.H24,
                    confidence_score=round(final_confidence, 3),
                    model_version="GeoAtlas-Ensemble-v1",
                    predicted_at=now,
                    resolve_at=resolve_time,
                    outcome=PredictionOutcome.PENDING
                )
                session.add(prediction)
                predictions_created += 1
                logger.info(f"Created live ML prediction: {event.title[:45]}... -> {asset.ticker} ({direction_str.upper()} {round(combined_change, 2)}%)")

        await session.commit()
        logger.info(f"Successfully generated {predictions_created} high-relevance live ML predictions!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(generate_live_predictions_async())
