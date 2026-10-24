"""Deduplication and merge script for existing duplicate Event rows in PostgreSQL.

Identifies duplicate event titles, merges linked articles, impacts, and tags into
the primary event record, and deletes redundant duplicate event rows.
"""

import asyncio
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import async_session_factory
from modules.events.models import (
    Event,
    EventArticle,
    EventImpact,
    EventTag,
    Prediction,
    EventReviewAction,
    EventTrainingExample,
    AlertNotification,
)


async def dedup_events():
    async with async_session_factory() as session:
        # Find duplicate event titles
        dup_titles_res = await session.execute(
            select(func.lower(func.trim(Event.title)), func.count(Event.id))
            .group_by(func.lower(func.trim(Event.title)))
            .having(func.count(Event.id) > 1)
        )
        dup_groups = dup_titles_res.all()
        print(f"Found {len(dup_groups)} distinct titles with duplicate event rows.")

        total_merged = 0
        total_deleted = 0

        for title_lower, count in dup_groups:
            # Fetch all events with this normalized title
            events_res = await session.execute(
                select(Event)
                .where(func.lower(func.trim(Event.title)) == title_lower)
                .order_by(Event.confidence_score.desc().nullslast(), Event.created_at.asc())
            )
            events = events_res.scalars().all()
            if len(events) <= 1:
                continue

            primary = events[0]
            duplicates = events[1:]

            primary_id = primary.id
            dup_ids = [d.id for d in duplicates]

            for dup_id in dup_ids:
                # 1. event_articles
                dup_ea_res = await session.execute(
                    select(EventArticle).where(EventArticle.event_id == dup_id)
                )
                dup_eas = dup_ea_res.scalars().all()
                for ea in dup_eas:
                    # check if already linked to primary
                    exists = await session.execute(
                        select(EventArticle).where(
                            EventArticle.event_id == primary_id,
                            EventArticle.article_id == ea.article_id,
                        )
                    )
                    if exists.scalar_one_or_none():
                        await session.delete(ea)
                    else:
                        ea.event_id = primary_id

                # 2. event_impacts
                dup_ei_res = await session.execute(
                    select(EventImpact).where(EventImpact.event_id == dup_id)
                )
                dup_eis = dup_ei_res.scalars().all()
                for ei in dup_eis:
                    exists = await session.execute(
                        select(EventImpact).where(
                            EventImpact.event_id == primary_id,
                            EventImpact.asset_id == ei.asset_id,
                        )
                    )
                    if exists.scalar_one_or_none():
                        await session.delete(ei)
                    else:
                        ei.event_id = primary_id

                # 3. event_tags
                dup_et_res = await session.execute(
                    select(EventTag).where(EventTag.event_id == dup_id)
                )
                dup_ets = dup_et_res.scalars().all()
                for et in dup_ets:
                    exists = await session.execute(
                        select(EventTag).where(
                            EventTag.event_id == primary_id,
                            EventTag.tag == et.tag,
                        )
                    )
                    if exists.scalar_one_or_none():
                        await session.delete(et)
                    else:
                        et.event_id = primary_id

                # 4. predictions
                await session.execute(
                    update(Prediction).where(Prediction.event_id == dup_id).values(event_id=primary_id)
                )

                # 5. event_review_actions
                await session.execute(
                    update(EventReviewAction).where(EventReviewAction.event_id == dup_id).values(event_id=primary_id)
                )

                # 6. event_training_examples
                await session.execute(
                    update(EventTrainingExample).where(EventTrainingExample.event_id == dup_id).values(event_id=primary_id)
                )

                # 7. alert_notifications
                await session.execute(
                    update(AlertNotification).where(AlertNotification.event_id == dup_id).values(event_id=primary_id)
                )

                # Delete duplicate event
                dup_event = await session.get(Event, dup_id)
                if dup_event:
                    await session.delete(dup_event)
                    total_deleted += 1

            total_merged += 1

        await session.commit()
        print(f"Successfully processed {total_merged} groups and deleted {total_deleted} duplicate event rows.")


if __name__ == "__main__":
    asyncio.run(dedup_events())
