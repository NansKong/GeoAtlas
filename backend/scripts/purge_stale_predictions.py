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
logger = logging.getLogger("purge_stale_predictions")

async def purge_orphan_predictions_async():
    logger.info("Purging orphan predictions whose events were deleted...")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get set of all valid event IDs
        events_res = await session.execute(select(Event.id))
        valid_event_ids = set(events_res.scalars().all())

        # Fetch all predictions
        preds_res = await session.execute(select(Prediction))
        all_preds = preds_res.scalars().all()

        orphans_deleted = 0
        for pred in all_preds:
            if pred.event_id not in valid_event_ids:
                await session.delete(pred)
                orphans_deleted += 1

        await session.commit()
        logger.info(f"Purged {orphans_deleted} orphan predictions!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(purge_orphan_predictions_async())
