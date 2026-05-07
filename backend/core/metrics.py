from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import Event, EventImpact, EventStatus, EventTrainingExample, NewsArticle

PUBLISHED_EVENT_STATUSES = (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * p))))
    return ordered[idx]


def _safe_set(metric: Gauge, value: Optional[float]) -> None:
    if value is not None:
        metric.set(float(value))


def collect_metrics_text() -> bytes:
    registry = CollectorRegistry()
    m_classification = Gauge(
        "geoatlas_event_classification_accuracy",
        "Share of review actions that ended in approve.",
        registry=registry,
    )
    m_latency_p95 = Gauge(
        "geoatlas_nlp_latency_p95_seconds",
        "p95 latency from article create to NLP processed timestamp.",
        registry=registry,
    )
    m_auto_approved_rate = Gauge(
        "geoatlas_events_auto_approved_rate",
        "Share of events that are auto-approved.",
        registry=registry,
    )
    m_review_backlog = Gauge(
        "geoatlas_review_queue_backlog",
        "Count of events pending human review.",
        registry=registry,
    )
    m_ingestion_freshness = Gauge(
        "geoatlas_news_ingestion_freshness_minutes",
        "Minutes since latest ingested article row.",
        registry=registry,
    )
    m_asset_coverage = Gauge(
        "geoatlas_asset_mapping_coverage",
        "Share of published events with at least one impact mapping.",
        registry=registry,
    )

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    with Session(engine) as session:
        total_reviewed = int(
            session.execute(
                select(func.count()).where(EventTrainingExample.review_action.in_(("approve", "reject")))
            ).scalar()
            or 0
        )
        approved = int(
            session.execute(
                select(func.count()).where(EventTrainingExample.review_action == "approve")
            ).scalar()
            or 0
        )
        if total_reviewed:
            m_classification.set(approved / total_reviewed)

        latency_rows = session.execute(
            select(NewsArticle.created_at, NewsArticle.nlp_processed_at)
            .where(NewsArticle.nlp_processed_at.is_not(None))
            .order_by(NewsArticle.nlp_processed_at.desc())
            .limit(2000)
        ).all()
        latency_values = [
            max(0.0, (processed_at - created_at).total_seconds())
            for created_at, processed_at in latency_rows
            if created_at is not None and processed_at is not None
        ]
        _safe_set(m_latency_p95, _percentile(latency_values, 0.95))

        total_events = int(session.execute(select(func.count()).select_from(Event)).scalar() or 0)
        auto_approved = int(
            session.execute(select(func.count()).where(Event.status == EventStatus.AUTO_APPROVED)).scalar() or 0
        )
        if total_events:
            m_auto_approved_rate.set(auto_approved / total_events)

        review_backlog = int(
            session.execute(select(func.count()).where(Event.status == EventStatus.PENDING_REVIEW)).scalar() or 0
        )
        m_review_backlog.set(review_backlog)

        latest_news = session.execute(
            select(NewsArticle.created_at).order_by(NewsArticle.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        if latest_news is not None:
            freshness = max(0.0, (datetime.now(timezone.utc) - latest_news).total_seconds() / 60.0)
            m_ingestion_freshness.set(freshness)

        published_events = int(
            session.execute(
                select(func.count()).select_from(Event).where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
            ).scalar()
            or 0
        )
        mapped_events = int(
            session.execute(
                select(func.count(func.distinct(EventImpact.event_id)))
                .join(Event, Event.id == EventImpact.event_id)
                .where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
            ).scalar()
            or 0
        )
        if published_events:
            m_asset_coverage.set(mapped_events / published_events)

    # ─── PROVIDER RESILIENCE METRICS ──────────────────────────────────────────
    from core.http import PROVIDERS, CircuitState

    m_provider_score = Gauge(
        "geoatlas_provider_health_score",
        "EMA composite health score (0.05-1.0)",
        ["provider"],
        registry=registry,
    )
    m_provider_latency = Gauge(
        "geoatlas_provider_latency_ms",
        "EMA latency in ms",
        ["provider"],
        registry=registry,
    )
    m_circuit_state = Gauge(
        "geoatlas_circuit_state",
        "Circuit: 0=CLOSED, 1=OPEN, 2=HALF_OPEN",
        ["provider"],
        registry=registry,
    )
    m_limiter_delay = Gauge(
        "geoatlas_limiter_delay_seconds",
        "Current adaptive limiter delay",
        ["provider"],
        registry=registry,
    )

    for pname, ctx in PROVIDERS.items():
        m_provider_score.labels(provider=pname).set(ctx.health.get_composite_score())
        m_provider_latency.labels(provider=pname).set(ctx.health.latency_ema)
        state_val = {CircuitState.CLOSED: 0, CircuitState.OPEN: 1, CircuitState.HALF_OPEN: 2}
        m_circuit_state.labels(provider=pname).set(state_val.get(ctx.breaker.state, 0))
        m_limiter_delay.labels(provider=pname).set(ctx.limiter.delay)

    # Snapshot & DB telemetry (populated by workers at runtime)
    Gauge("geoatlas_db_buffer_size", "Current DB write buffer size", registry=registry)
    Gauge("geoatlas_snapshot_latency_ms", "Last snapshot cycle duration", registry=registry)
    Gauge("geoatlas_ml_timeouts_total", "Total ML inference timeouts", registry=registry)

    return generate_latest(registry)
