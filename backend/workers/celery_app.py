from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "geoatlas",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "workers.ingestion",
        "workers.event_pipeline",
        "workers.review_feedback",
        "workers.predictions",
        "workers.alerts",
        "workers.feature_state",
        "workers.cleanup",
    ],
)

import ssl

broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE} if (settings.CELERY_BROKER_URL and settings.CELERY_BROKER_URL.startswith("rediss://")) else None
redis_backend_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE} if (settings.CELERY_RESULT_BACKEND and settings.CELERY_RESULT_BACKEND.startswith("rediss://")) else None

celery_app.conf.update(
    broker_use_ssl=broker_use_ssl,
    redis_backend_use_ssl=redis_backend_use_ssl,
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
    # ── Tier-1 Wire Services (offset: :00, :10, :20, :30, :40, :50) ───────────
    "fetch-reuters-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.reuters.com/reuters/topNews"],
        "schedule": crontab(minute="0,10,20,30,40,50"),
    },
    "fetch-ap-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rsshub.app/apnews/topics/apf-intlnews"],
        "schedule": crontab(minute="0,10,20,30,40,50"),
    },
    "fetch-aljazeera-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.aljazeera.com/xml/rss/all.xml"],
        "schedule": crontab(minute="0,10,20,30,40,50"),
    },
    "fetch-bbc-world-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.bbci.co.uk/news/world/rss.xml"],
        "schedule": crontab(minute="0,10,20,30,40,50"),
    },
    "fetch-bbc-top-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.bbci.co.uk/news/rss.xml"],
        "schedule": crontab(minute="0,10,20,30,40,50"),
    },

    # ── Print & International Papers (offset: :02, :12, :22, :32, :42, :52) ───
    "fetch-nyt-world-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
        "schedule": crontab(minute="2,12,22,32,42,52"),
    },
    "fetch-nyt-business-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"],
        "schedule": crontab(minute="2,12,22,32,42,52"),
    },
    "fetch-guardian-world-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.theguardian.com/world/rss"],
        "schedule": crontab(minute="2,12,22,32,42,52"),
    },
    "fetch-guardian-business-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.theguardian.com/uk/business/rss"],
        "schedule": crontab(minute="2,12,22,32,42,52"),
    },
    "fetch-dw-world-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rss.dw.com/xml/rss-en-world"],
        "schedule": crontab(minute="2,12,22,32,42,52"),
    },

    # ── Broadcasters & Asia (offset: :04, :14, :24, :34, :44, :54) ────────────
    "fetch-npr-news-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.npr.org/1001/rss.xml"],
        "schedule": crontab(minute="4,14,24,34,44,54"),
    },
    "fetch-npr-world-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://feeds.npr.org/1004/rss.xml"],
        "schedule": crontab(minute="4,14,24,34,44,54"),
    },
    "fetch-dw-business-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://rss.dw.com/xml/rss-en-bus"],
        "schedule": crontab(minute="4,14,24,34,44,54"),
    },
    "fetch-france24-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.france24.com/en/rss"],
        "schedule": crontab(minute="4,14,24,34,44,54"),
    },
    "fetch-scmp-rss-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://www.scmp.com/rss/91/feed"],
        "schedule": crontab(minute="4,14,24,34,44,54"),
    },

    # ── Google News Aggregator (offset: :06, :16, :26, :36, :46, :56) ─────────
    "fetch-google-news-business-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"],
        "schedule": crontab(minute="6,16,26,36,46,56"),
    },
    "fetch-google-news-world-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"],
        "schedule": crontab(minute="6,16,26,36,46,56"),
    },
    "fetch-google-news-qatar-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://news.google.com/rss/search?q=Qatar+(Iran+OR+attack+OR+security+OR+energy)&hl=en-US&gl=US&ceid=US:en"],
        "schedule": crontab(minute="7,17,27,37,47,57"),
    },
    "fetch-google-news-uae-every-10-min": {
        "task": "workers.ingestion.fetch_rss",
        "args": ["https://news.google.com/rss/search?q=(UAE+OR+Dubai+OR+Abu+Dhabi)+(Iran+OR+attack+OR+security+OR+conflict)&hl=en-US&gl=US&ceid=US:en"],
        "schedule": crontab(minute="7,17,27,37,47,57"),
    },

    # ── APIs & Structured Ingestion (offset: :08, :18, :28, :38, :48, :58) ───
    "fetch-newsapi-every-10-min": {
        "task": "workers.ingestion.fetch_newsapi",
        "schedule": crontab(minute="8,18,28,38,48,58"),
    },
    "fetch-gdelt-every-10-min": {
        "task": "workers.ingestion.fetch_gdelt",
        "schedule": crontab(minute="8,18,28,38,48,58"),
    },
    "fetch-eventregistry-every-10-min": {
        "task": "workers.ingestion.fetch_eventregistry",
        "schedule": crontab(minute="8,18,28,38,48,58"),
    },
    "fetch-mediastack-every-10-min": {
        "task": "workers.ingestion.fetch_mediastack",
        "schedule": crontab(minute="8,18,28,38,48,58"),
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
    "purge-stale-data-daily": {
        "task": "workers.cleanup.purge_old_data",
        "args": [30],
        "schedule": crontab(hour=2, minute=30),
    },
}
