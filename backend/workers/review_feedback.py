from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import (
    Event,
    EventArticle,
    EventImpact,
    EventReviewAction,
    EventStatus,
    EventTag,
    EventTrainingExample,
    NewsArticle,
)
from modules.market.models import Asset
from workers.celery_app import celery_app


def _event_tags(session: Session, event_id) -> list[str]:
    result = session.execute(
        select(EventTag.tag).where(EventTag.event_id == event_id).order_by(EventTag.tag.asc())
    )
    return list(result.scalars().all())


def _event_impacts(session: Session, event_id) -> list[dict]:
    result = session.execute(
        select(EventImpact, Asset)
        .join(Asset, Asset.id == EventImpact.asset_id)
        .where(EventImpact.event_id == event_id)
        .order_by(EventImpact.confidence_score.desc())
    )
    return [
        {
            "ticker": asset.ticker,
            "name": asset.name,
            "impact_direction": impact.impact_direction.value,
            "impact_strength": impact.impact_strength,
            "confidence_score": impact.confidence_score,
        }
        for impact, asset in result.all()
    ]


@celery_app.task(name="workers.review_feedback.backfill_training_examples", bind=True, max_retries=3)
def backfill_training_examples(self, batch_size: int = 250):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    created = 0
    updated_events = 0
    with Session(engine) as session:
        events = session.execute(
            select(Event)
            .where(Event.status.in_([EventStatus.HUMAN_APPROVED, EventStatus.REJECTED]))
            .order_by(Event.created_at.desc())
            .limit(batch_size)
        ).scalars().all()

        for event in events:
            articles = session.execute(
                select(NewsArticle)
                .join(EventArticle, EventArticle.article_id == NewsArticle.id)
                .where(EventArticle.event_id == event.id)
            ).scalars().all()
            if not articles:
                continue

            tags = _event_tags(session, event.id)
            impacts = _event_impacts(session, event.id)
            review_action = "approve" if event.status == EventStatus.HUMAN_APPROVED else "reject"
            reviewer_id = session.execute(
                select(EventReviewAction.reviewer_id)
                .where(
                    EventReviewAction.event_id == event.id,
                    EventReviewAction.action == review_action,
                )
                .order_by(EventReviewAction.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if reviewer_id is None:
                continue

            for article in articles:
                exists = session.execute(
                    select(EventTrainingExample).where(
                        EventTrainingExample.event_id == event.id,
                        EventTrainingExample.article_id == article.id,
                        EventTrainingExample.review_action == review_action,
                    )
                ).scalar_one_or_none()
                if exists:
                    continue

                session.add(
                    EventTrainingExample(
                        event_id=event.id,
                        article_id=article.id,
                        reviewer_id=reviewer_id,
                        review_action=review_action,
                        label_event_type=event.event_type.value if event.status == EventStatus.HUMAN_APPROVED else None,
                        label_status=event.status.value,
                        language_code=article.language_code,
                        title=event.title,
                        article_title=article.title,
                        article_content=article.content,
                        source=article.source,
                        url=article.url,
                        country=event.country,
                        region=event.region,
                        severity=event.severity,
                        confidence_score=event.confidence_score,
                        tags=tags,
                        affected_assets=impacts,
                        metadata_={
                            "event_source": event.source,
                            "event_source_url": event.source_url,
                            "article_published_at": article.published_at.isoformat() if article.published_at else None,
                            "reviewed_at": datetime.now(timezone.utc).isoformat(),
                            "backfilled": True,
                        },
                    )
                )
                created += 1
            updated_events += 1

        session.commit()

    result = {"updated_events": updated_events, "created_examples": created}
    return result


@celery_app.task(name="workers.review_feedback.export_training_examples_jsonl", bind=True, max_retries=2)
def export_training_examples_jsonl(self, output_path: str = "data/training_examples.jsonl", limit: int = 5000):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    resolved = Path(output_path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[1] / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session, resolved.open("w", encoding="utf-8") as handle:
        rows = session.execute(
            select(EventTrainingExample)
            .order_by(EventTrainingExample.created_at.desc())
            .limit(limit)
        ).scalars().all()

        for row in rows:
            handle.write(
                json.dumps(
                    {
                        "id": str(row.id),
                        "event_id": str(row.event_id),
                        "article_id": str(row.article_id),
                        "reviewer_id": str(row.reviewer_id),
                        "review_action": row.review_action,
                        "label_event_type": row.label_event_type,
                        "label_status": row.label_status,
                        "language_code": row.language_code,
                        "title": row.title,
                        "article_title": row.article_title,
                        "article_content": row.article_content,
                        "source": row.source,
                        "url": row.url,
                        "country": row.country,
                        "region": row.region,
                        "severity": row.severity,
                        "confidence_score": row.confidence_score,
                        "tags": row.tags or [],
                        "affected_assets": row.affected_assets or [],
                        "metadata": row.metadata_ or {},
                        "created_at": row.created_at.isoformat(),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    return {"exported": len(rows), "path": str(resolved)}
