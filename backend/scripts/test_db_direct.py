import os
import sys
import time
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from modules.predictions.models import Prediction
from modules.predictions.service import list_predictions

async def main():
    t0 = time.time()
    print("Testing DB connection...")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        items = await list_predictions(session, limit=4, published_only=True)
        t1 = time.time()
        print(f"Fetched {len(items)} predictions in {round((t1 - t0)*1000, 2)} ms!")
        for item in items:
            print(f"- {item.ticker} ({item.predicted_direction.upper()} {item.predicted_change_pct}%): {item.event_title}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
