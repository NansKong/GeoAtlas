import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import NewsArticle
from modules.market.models import MarketPrice
from modules.boards.models import AlertNotification
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.cleanup.purge_old_data", bind=True, max_retries=2)
def purge_old_data(self, days: int = 30) -> dict:
    """
    Deletes raw news articles, market price ticks, and alert notifications older than `days` (default 30).
    Runs automatically via Celery Beat daily schedule to prevent database bloat.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logger.info(f"Starting database retention cleanup for records older than {cutoff.isoformat()} ({days} days)...")

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    stats = {}

    try:
        with Session(engine) as session:
            try:
                # 1. Purge old market prices
                stmt_prices = delete(MarketPrice).where(MarketPrice.timestamp < cutoff)
                res_prices = session.execute(stmt_prices)
                stats["market_prices_deleted"] = res_prices.rowcount

                # 2. Purge old news articles (foreign key event_articles cascades automatically)
                stmt_news = delete(NewsArticle).where(NewsArticle.created_at < cutoff)
                res_news = session.execute(stmt_news)
                stats["news_articles_deleted"] = res_news.rowcount

                # 3. Purge old alert notifications
                stmt_alerts = delete(AlertNotification).where(AlertNotification.created_at < cutoff)
                res_alerts = session.execute(stmt_alerts)
                stats["alert_notifications_deleted"] = res_alerts.rowcount

                session.commit()
                logger.info(f"Database retention cleanup committed successfully: {stats}")
            except Exception as exc:
                session.rollback()
                logger.error(f"Database cleanup failed: {exc}", exc_info=True)
                raise self.retry(exc=exc, countdown=60)
    finally:
        engine.dispose()

    return stats
