import argparse
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import NewsArticle
from modules.market.models import MarketPrice
from modules.boards.models import AlertNotification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup")


def main():
    parser = argparse.ArgumentParser(description="Purge stale database records older than N days.")
    parser.add_argument("--days", type=int, default=30, help="Retention window in days (default: 30)")
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM FULL to reclaim physical disk space")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    logger.info(f"Purging data older than {cutoff.isoformat()} ({args.days} days retention)...")

    sync_url = settings.DATABASE_URL_SYNC
    if not sync_url and settings.DATABASE_URL:
        sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    if not sync_url:
        logger.error("DATABASE_URL / DATABASE_URL_SYNC is not set.")
        return

    engine = create_engine(sync_url, pool_pre_ping=True)

    with Session(engine) as session:
        # 1. Market prices
        res_prices = session.execute(delete(MarketPrice).where(MarketPrice.timestamp < cutoff))
        logger.info(f"Deleted {res_prices.rowcount} market price records.")

        # 2. News articles
        res_news = session.execute(delete(NewsArticle).where(NewsArticle.created_at < cutoff))
        logger.info(f"Deleted {res_news.rowcount} news articles.")

        # 3. Alert notifications
        res_alerts = session.execute(delete(AlertNotification).where(AlertNotification.created_at < cutoff))
        logger.info(f"Deleted {res_alerts.rowcount} alert notifications.")

        session.commit()
        logger.info("Deletion committed successfully.")

    if args.vacuum:
        logger.info("Running VACUUM FULL on pruned tables to reclaim disk space...")
        # Vacuum requires autocommit mode (outside a transaction block)
        vacuum_engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
        with vacuum_engine.connect() as conn:
            for tbl in ["market_prices", "news_articles", "alert_notifications"]:
                logger.info(f"Vacuuming {tbl}...")
                try:
                    conn.execute(text(f"VACUUM FULL {tbl}"))
                    logger.info(f"VACUUM FULL {tbl} completed.")
                except Exception as e:
                    logger.warning(f"Could not vacuum {tbl}: {e}")

    logger.info("Database cleanup completed successfully.")


if __name__ == "__main__":
    main()
