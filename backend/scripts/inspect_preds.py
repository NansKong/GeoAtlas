import os
import sys
import asyncio
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from modules.events.models import Event
from modules.predictions.models import Prediction

async def main():
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get all predictions with event titles
        res = await session.execute(
            select(Prediction.id, Prediction.event_id, Event.title)
            .outerjoin(Event, Event.id == Prediction.event_id)
            .order_by(Prediction.predicted_at.desc())
            .limit(20)
        )
        rows = res.all()
        print(f"Total predictions fetched: {len(rows)}")
        for pid, eid, title in rows:
            print(f"Pred ID: {pid} | Event ID: {eid} | Title: {title}")

        # Delete any prediction whose title contains 'dating', 'bar-b-que', or 'wanna bet'
        deleted = 0
        for pid, eid, title in rows:
            t = (title or "").lower()
            if any(k in t for k in ["dating", "bar-b-que", "wanna bet", "dinosaur"]):
                await session.execute(delete(Prediction).where(Prediction.id == pid))
                if eid:
                    await session.execute(delete(Event).where(Event.id == eid))
                deleted += 1

        await session.commit()
        print(f"Explicitly deleted {deleted} non-macro predictions!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
