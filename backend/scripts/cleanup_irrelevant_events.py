import os
import sys
import asyncio
import logging
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from modules.events.models import Event, EventImpact
from modules.predictions.models import Prediction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup_irrelevant_events")

IRRELEVANT_KEYWORDS = [
    "dating", "bar-b-que", "barbeque", "restaurant", "party", " Substacks", "west village", 
    "wanna bet", "cholesterol", "meningitis", "recipe", "fashion", "celebrity", "movie", 
    "box office", "grammy", "oscar", "sports", "nfl", "nba", "mlb", "man city", "arsenal", 
    "chelsea", "liverpool", "barcelona", "real madrid", "premier league", "champions league",
    "concert", "song", "album", "golf", "tennis"
]

# Valid macro geopolitical event categories
MACRO_EVENT_TYPES = ["conflict", "sanction", "trade_policy", "economic_data", "energy_disruption", "election"]

async def cleanup_irrelevant_events_async():
    logger.info("Purging non-geopolitical and non-macro events from database...")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        events_res = await session.execute(select(Event))
        events = events_res.scalars().all()
        removed_count = 0

        for event in events:
            text = f"{event.title or ''} {event.description or ''}".lower()
            event_type_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type).lower()
            
            is_irrelevant = (
                any(kw in text for kw in IRRELEVANT_KEYWORDS) or 
                (event_type_str not in MACRO_EVENT_TYPES and not any(k in text for k in ["iran", "trump", "war", "oil", "tariff", "china", "sanction", "fed", "inflation", "military", "ceasefire", "strait"]))
            )

            if is_irrelevant:
                # Delete predictions for this event
                await session.execute(delete(Prediction).where(Prediction.event_id == event.id))
                # Delete event impacts
                await session.execute(delete(EventImpact).where(EventImpact.event_id == event.id))
                # Delete event
                await session.delete(event)
                removed_count += 1
                logger.info(f"Removed non-geopolitical event: {event.title}")

        await session.commit()
        logger.info(f"Successfully cleaned up {removed_count} non-geopolitical events from database!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(cleanup_irrelevant_events_async())
