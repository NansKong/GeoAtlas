from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "geoatlas",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["workers.ingestion", "workers.event_pipeline", "workers.review_feedback", "workers.predictions", "workers.alerts", "workers.feature_state"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# ─── Beat Schedule (news ingestion every 10 min) ─────────────────────────────

celery_app.conf.beat_schedule = {
    "fetch-newsapi-every-10-min": {
        "task": "workers.ingestion.fetch_newsapi",
        "schedule": crontab(minute="*/10"),
    },
    "fetch-gdelt-every-10-min": {
        "task": "workers.ingestion.fetch_gdelt",
        "schedule": crontab(minute="*/10"),
    },
    "fetch-eventregistry-every-10-min": {
        "task": "workers.ingestion.fetch_eventregistry",
        "schedule": crontab(minute="*/10"),
    },
    "fetch-mediastack-every-10-min": {
        "task": "workers.ingestion.fetch_mediastack",
        "schedule": crontab(minute="*/10"),
    },
    "fetch-reuters-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.reuters.com/reuters/topNews"],
        "schedule": crontab(minute="*/10"),
    },
    "fetch-ap-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rsshub.app/apnews/topics/apf-intlnews"],
        "schedule": crontab(minute="*/10"),
    },
    "fetch-aljazeera-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.aljazeera.com/xml/rss/all.xml"],
        "schedule": crontab(minute="*/10"),
    },
    "process-unprocessed-articles-every-5-min": {
        "task": "workers.event_pipeline.process_unprocessed_articles",
        "kwargs": {"batch_size": 200},
        "schedule": crontab(minute="*/5"),
    },
    "seed-knowledge-graph-daily": {
        "task": "workers.ingestion.seed_knowledge_graph",
        "schedule": crontab(hour=3, minute=10),
    },
    "verify-due-predictions-hourly": {
        "task": "workers.predictions.verify_due_predictions",
        "schedule": crontab(minute=12),
    },
    "calculate-live-features-every-3-min": {
        "task": "workers.feature_state.calculate_7d_rolling_features",
        "schedule": crontab(minute="*/3"),
    },
}
