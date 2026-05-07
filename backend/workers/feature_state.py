import logging
import json
import uuid
import redis
from datetime import datetime, timezone, timedelta
import numpy as np

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.market.models import Asset, MarketPrice
from modules.events.models import EventImpact, Event
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

@celery_app.task(name="workers.feature_state.calculate_7d_rolling_features", bind=True, max_retries=2)
def calculate_7d_rolling_features(self):
    """
    Continually runs to update ML Features in Redis.
    """
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    
    with Session(engine) as session:
        assets = session.execute(select(Asset)).scalars().all()
        now = datetime.now(timezone.utc)
        
        pipeline = r.pipeline()
        processed = 0

        for asset in assets:
            # 1. Fetch Prices (Last 30 days to compute 14d MAs and 7d returns)
            prices = session.execute(
                select(MarketPrice)
                .where(MarketPrice.asset_id == asset.id)
                .order_by(MarketPrice.timestamp.desc())
                .limit(30)
            ).scalars().all()
            
            if not prices:
                continue
                
            prices_asc = list(reversed(prices))
            df_prices = pd.DataFrame([{
                "date": p.timestamp.date(),
                "close": float(p.close)
            } for p in prices_asc])
            
            # Aggregate to daily if multiple hits exist (last price of day)
            df_prices = df_prices.groupby("date").last().reset_index()
            
            # Market Features
            df_prices["return_7d"] = np.log(df_prices["close"] / df_prices["close"].shift(7)).fillna(0)
            df_prices["return_1d"] = np.log(df_prices["close"] / df_prices["close"].shift(1)).fillna(0)
            df_prices["volatility_7d"] = df_prices["close"].pct_change().rolling(7, min_periods=1).std().fillna(0)
            df_prices["ma_14"] = df_prices["close"].rolling(14, min_periods=1).mean().fillna(0)
            
            latest_market = df_prices.iloc[-1]
            
            # 2. Fetch Events (Last 14 days to compute 7d lags and rolling avgs)
            t_back = now - timedelta(days=14)
            events_data = session.execute(
                select(Event.published_at, EventImpact.impact_strength, Event.metadata_)
                .join(EventImpact, Event.id == EventImpact.event_id)
                .where(
                    EventImpact.asset_id == asset.id,
                    Event.published_at >= t_back
                )
            ).all()
            
            # Event Features default
            event_count = 0
            event_spike = 0
            sentiment_trend = 0
            max_abs_goldstein = 0.0
            sentiment_momentum = 0.0
            event_x_return = 0.0
            max_sent_lag_1 = 0.0
            max_sent_lag_2 = 0.0
            sentiment_x_volatility = 0.0
            
            if events_data:
                rows = []
                for pub_at, sent, meta in events_data:
                    g_scale = meta.get("goldstein_scale", 0.0) if meta else 0.0
                    rows.append({
                        "date": pub_at.date(),
                        "sentiment": float(sent) if sent else 0.0,
                        "goldstein": float(g_scale) if g_scale else 0.0,
                        "abs_sentiment": abs(float(sent)) if sent else 0.0,
                        "abs_goldstein": abs(float(g_scale)) if g_scale else 0.0
                    })
                df_events = pd.DataFrame(rows)
                
                # Daily aggregation matching Phase 4
                df_daily = df_events.groupby("date").agg(
                    event_count=("sentiment", "count"),
                    avg_sentiment=("sentiment", "mean"),
                    max_abs_goldstein=("abs_goldstein", "max"),
                    max_abs_sentiment=("abs_sentiment", "max")
                ).reindex(pd.date_range(end=now.date(), periods=14)).fillna(0).reset_index()
                
                # Mometum & Trailing variables
                df_daily["sentiment_momentum"] = df_daily["avg_sentiment"].diff().fillna(0)
                df_daily["sentiment_trend"] = np.sign(df_daily["sentiment_momentum"])
                df_daily["event_spike"] = (df_daily["event_count"] > df_daily["event_count"].rolling(7, min_periods=1).mean()).astype(int)
                
                df_daily["max_sent_lag_1"] = df_daily["max_abs_sentiment"].shift(1).fillna(0)
                df_daily["max_sent_lag_2"] = df_daily["max_abs_sentiment"].shift(2).fillna(0)
                
                latest_evt = df_daily.iloc[-1]
                
                event_count = int(latest_evt["event_count"])
                event_spike = int(latest_evt["event_spike"])
                sentiment_trend = float(latest_evt["sentiment_trend"])
                max_abs_goldstein = float(latest_evt["max_abs_goldstein"])
                max_sent_lag_1 = float(latest_evt["max_sent_lag_1"])
                max_sent_lag_2 = float(latest_evt["max_sent_lag_2"])
                sentiment_momentum = float(latest_evt["sentiment_momentum"])
                
            # Interactions
            volatility_7d = float(latest_market["volatility_7d"])
            return_1d = float(latest_market["return_1d"])
            
            sentiment_x_volatility = sentiment_momentum * volatility_7d
            event_x_return = float(event_count) * return_1d
            
            features = {
                "7d_vol": volatility_7d, # keep fallback names
                "volatility_7d": volatility_7d,
                "sentiment_momentum": sentiment_momentum,
                "event_count": event_count,
                "event_spike": event_spike,
                "max_abs_goldstein": max_abs_goldstein,
                "sentiment_trend": sentiment_trend,
                "max_sent_lag_1": max_sent_lag_1,
                "max_sent_lag_2": max_sent_lag_2,
                "sentiment_x_volatility": sentiment_x_volatility,
                "event_x_return": event_x_return,
                "ma_14": float(latest_market["ma_14"]),
                "return_7d": float(latest_market["return_7d"]),
                "vol_rank": 0.5 # Default rank across isolated single queries
            }
            
            feature_payload = {
                "ts": now.isoformat(),
                "features": features
            }
            
            key = f"feature:asset:{asset.id}"
            pipeline.set(key, json.dumps(feature_payload), ex=300) # 5 min TTL
            processed += 1
            
        pipeline.execute()
            
    logger.info("Updated rolling features for %d assets", processed)
    return {"status": "ok", "assets_processed": processed}
