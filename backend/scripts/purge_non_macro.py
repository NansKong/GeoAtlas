import os
import sys
import asyncio
import logging
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from modules.events.models import Event
from modules.predictions.models import Prediction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("purge_non_macro")

IRRELEVANT_KEYWORDS = [
    "dating", "bar-b-que", "barbeque", "restaurant", "party", "substack", "wanna bet", 
    "cholesterol", "meningitis", "recipe", "fashion", "celebrity", "movie", "box office", 
    "grammy", "oscar", "sports", "nfl", "nba", "mlb", "man city", "arsenal", "chelsea", 
    "liverpool", "barcelona", "real madrid", "premier league", "champions league", "concert"
]

async def main():
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Direct SQL delete of predictions joining event titles with keyword matches
        res = await session.execute(
            select(Prediction, Event.title)
            .join(Event, Event.id == Prediction.event_id)
        )
        rows = res.all()
        to_delete_pred_ids = []
        to_delete_event_ids = set()

        for pred, title in rows:
            t_lower = (title or "").lower()
            if any(kw in t_lower for kw in IRRELEVANT_KEYWORDS):
                to_delete_pred_ids.append(pred.id)
                to_delete_event_ids.add(pred.event_id)

        if to_delete_pred_ids:
            await session.execute(delete(Prediction).where(Prediction.id.in_(to_delete_pred_ids)))
        if to_delete_event_ids:
            await session.execute(delete(Event).where(Event.id.in_(list(to_delete_event_ids))))

        await session.commit()
        logger.info(f"Successfully deleted {len(to_delete_pred_ids)} non-macro predictions and {len(to_delete_event_ids)} non-macro events!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
