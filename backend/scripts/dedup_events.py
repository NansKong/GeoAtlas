"""Deduplication and merge script for existing duplicate Event rows in PostgreSQL.

Identifies duplicate event titles, merges linked articles, impacts, and tags into
the primary event record, and deletes redundant duplicate event rows.
"""

import asyncio
from sqlalchemy import text
from core.database import AsyncSessionFactory


async def dedup_events():
    async with AsyncSessionFactory() as session:
        # 1. Find all duplicate titles
        dup_titles_res = await session.execute(
            text("""
                SELECT lower(trim(title)) AS norm_title, count(id) AS cnt
                FROM events
                GROUP BY lower(trim(title))
                HAVING count(id) > 1;
            """)
        )
        dup_groups = dup_titles_res.fetchall()
        print(f"Found {len(dup_groups)} distinct title groups with duplicates in events table.")

        total_merged = 0
        total_deleted = 0

        for row in dup_groups:
            norm_title = row.norm_title
            # Fetch all event ids in this group, ordered with primary first
            ev_res = await session.execute(
                text("""
                    SELECT id FROM events
                    WHERE lower(trim(title)) = :norm_title
                    ORDER BY confidence_score DESC NULLS LAST, created_at ASC;
                """),
                {"norm_title": norm_title},
            )
            event_ids = [r.id for r in ev_res.fetchall()]
            if len(event_ids) <= 1:
                continue

            primary_id = event_ids[0]
            dup_ids = event_ids[1:]

            for dup_id in dup_ids:
                # Re-link or clean event_articles
                # First delete any duplicate article mappings that would violate primary key / unique
                await session.execute(
                    text("""
                        DELETE FROM event_articles ea_dup
                        WHERE ea_dup.event_id = :dup_id
                          AND EXISTS (
                              SELECT 1 FROM event_articles ea_pri
                              WHERE ea_pri.event_id = :pri_id
                                AND ea_pri.article_id = ea_dup.article_id
                          );
                    """),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )
                await session.execute(
                    text("UPDATE event_articles SET event_id = :pri_id WHERE event_id = :dup_id;"),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )

                # Re-link or clean event_impacts
                await session.execute(
                    text("""
                        DELETE FROM event_impacts ei_dup
                        WHERE ei_dup.event_id = :dup_id
                          AND EXISTS (
                              SELECT 1 FROM event_impacts ei_pri
                              WHERE ei_pri.event_id = :pri_id
                                AND ei_pri.asset_id = ei_dup.asset_id
                          );
                    """),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )
                await session.execute(
                    text("UPDATE event_impacts SET event_id = :pri_id WHERE event_id = :dup_id;"),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )

                # Re-link or clean event_tags
                await session.execute(
                    text("""
                        DELETE FROM event_tags et_dup
                        WHERE et_dup.event_id = :dup_id
                          AND EXISTS (
                              SELECT 1 FROM event_tags et_pri
                              WHERE et_pri.event_id = :pri_id
                                AND et_pri.tag = et_dup.tag
                          );
                    """),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )
                await session.execute(
                    text("UPDATE event_tags SET event_id = :pri_id WHERE event_id = :dup_id;"),
                    {"dup_id": dup_id, "pri_id": primary_id},
                )

                # Re-link other foreign keys
                for tbl in ["predictions", "event_review_actions", "event_training_examples", "alert_notifications"]:
                    await session.execute(
                        text(f"UPDATE {tbl} SET event_id = :pri_id WHERE event_id = :dup_id;"),
                        {"dup_id": dup_id, "pri_id": primary_id},
                    )

                # Finally delete the duplicate event row
                await session.execute(
                    text("DELETE FROM events WHERE id = :dup_id;"),
                    {"dup_id": dup_id},
                )
                total_deleted += 1

            total_merged += 1

        await session.commit()
        print(f"Dedup complete: successfully merged {total_merged} groups and deleted {total_deleted} duplicate event rows.")


if __name__ == "__main__":
    asyncio.run(dedup_events())
