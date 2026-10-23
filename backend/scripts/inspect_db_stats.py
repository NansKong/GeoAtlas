import asyncio
from sqlalchemy import text
from core.database import AsyncSessionFactory


async def inspect():
    async with AsyncSessionFactory() as session:
        # Table sizes and counts
        tables = [
            "news_articles",
            "market_prices",
            "events",
            "event_articles",
            "event_impacts",
            "predictions",
            "kg_entities",
            "kg_relationships",
            "users",
        ]
        print("\n--- TABLE SIZES & COUNTS ---")
        for t in tables:
            try:
                cnt = (await session.execute(text(f"SELECT COUNT(1) FROM {t}"))).scalar()
                size = (await session.execute(text(f"SELECT pg_size_pretty(pg_total_relation_size('{t}'))"))).scalar()
                print(f"{t:20s}: {cnt:>8} rows | {size:>10}")
            except Exception as e:
                print(f"{t:20s}: error {e}")

        # Date ranges
        print("\n--- DATE RANGES ---")
        try:
            res = (await session.execute(text("SELECT MIN(created_at), MAX(created_at) FROM news_articles"))).fetchone()
            print(f"news_articles created_at: min={res[0]}, max={res[1]}")
        except Exception as e:
            print("news_articles range error:", e)

        try:
            res = (await session.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM market_prices"))).fetchone()
            print(f"market_prices timestamp : min={res[0]}, max={res[1]}")
        except Exception as e:
            print("market_prices range error:", e)

        try:
            res = (await session.execute(text("SELECT MIN(created_at), MAX(created_at) FROM events"))).fetchone()
            print(f"events created_at        : min={res[0]}, max={res[1]}")
        except Exception as e:
            print("events range error:", e)


if __name__ == "__main__":
    asyncio.run(inspect())
