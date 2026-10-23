"""
Historical Event Re-tagger & Migration Script.

Applies the high-precision geo_tagger to all historical events.
Supports:
    python scripts/retag_historical_events.py --dry-run
    python scripts/retag_historical_events.py --apply
"""

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from core.database import AsyncSessionFactory
from modules.events.models import Event
from workers.geo_tagger import extract_countries, strip_publisher_suffix


async def retag_events(apply: bool = False, sample_limit: int = 15):
    print("\n" + "=" * 78)
    print("HISTORICAL EVENT GEO-TAG RE-EVALUATION")
    print(f"MODE: {'APPLY (COMMITTING TO DATABASE)' if apply else 'DRY RUN (SIMULATION ONLY - NO WRITES)'}")
    print("=" * 78 + "\n")

    async with AsyncSessionFactory() as session:
        # Fetch all events
        query = select(Event.id, Event.title, Event.description, Event.source, Event.country).order_by(Event.created_at.desc())
        res = await session.execute(query)
        rows = res.fetchall()

        total = len(rows)
        print(f"Total events found in database: {total}\n")

        before_counts: Counter[str] = Counter()
        after_counts: Counter[str] = Counter()
        changed_count = 0
        us_before = 0
        us_after = 0

        diff_samples = []

        for event_id, title, desc, source, old_country in rows:
            before_counts[old_country or "Unknown"] += 1
            if old_country == "United States":
                us_before += 1

            new_primary, secondary = extract_countries(
                title=title or "",
                body=desc or "",
                source=source,
            )
            resolved_country = new_primary or "Unknown"
            after_counts[resolved_country] += 1
            if resolved_country == "United States":
                us_after += 1

            if resolved_country != (old_country or "Unknown"):
                changed_count += 1
                if len(diff_samples) < sample_limit:
                    clean_t = strip_publisher_suffix(title or "", source)
                    diff_samples.append({
                        "id": str(event_id)[:8],
                        "title": clean_t[:65],
                        "old": old_country or "None",
                        "new": resolved_country,
                        "secondary": secondary,
                    })

        print("--- BEFORE vs AFTER COUNTRY DISTRIBUTION (TOP 10) ---")
        top_before = before_counts.most_common(10)
        top_after = after_counts.most_common(10)

        print(f"{'Old Country':<25} {'Count':>6}   |   {'New Country':<25} {'Count':>6}")
        print("-" * 68)
        for i in range(max(len(top_before), len(top_after))):
            b_name, b_cnt = top_before[i] if i < len(top_before) else ("", "")
            a_name, a_cnt = top_after[i] if i < len(top_after) else ("", "")
            print(f"{b_name:<25} {b_cnt:>6}   |   {a_name:<25} {a_cnt:>6}")

        print("-" * 68)
        us_pct_before = (us_before / total) * 100 if total else 0
        us_pct_after = (us_after / total) * 100 if total else 0
        print(f"\nUnited States Event Count: {us_before} ({us_pct_before:.1f}%) -> {us_after} ({us_pct_after:.1f}%)")
        print(f"Total Events with Changed Tags: {changed_count} / {total} ({(changed_count/total)*100:.1f}%)")

        print(f"\n--- SAMPLE TRANSFORMATIONS ({len(diff_samples)}) ---")
        for s in diff_samples:
            sec_str = f" [actors: {', '.join(s['secondary'])}]" if s['secondary'] else ""
            print(f"[{s['id']}] {s['old']:<16} -> {s['new']:<14}{sec_str} | {s['title']}")

        if not apply:
            print("\n" + "=" * 78)
            print("DRY RUN COMPLETE. 0 rows updated in database.")
            print("Run with --apply to commit these changes to PostgreSQL in a transaction.")
            print("=" * 78 + "\n")
            return

        # APPLY MODE
        print("\nApplying changes to database in a transaction...")
        update_count = 0
        changed_count = 0
        for event_id, title, desc, source, old_country in rows:
            new_primary, _ = extract_countries(
                title=title or "",
                body=desc or "",
                source=source,
            )
            if new_primary != old_country:
                changed_count += 1
            await session.execute(
                text("""
                UPDATE events
                SET country = :new_country,
                    pipeline_version = 2
                WHERE id = :id;
                """),
                {"new_country": new_primary, "id": event_id},
            )
            update_count += 1

        await session.commit()
        print(f"SUCCESS: Successfully processed {update_count} events (tags modified on {changed_count} rows) with pipeline_version = 2.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Historical event re-tagger")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Simulate without applying (default)")
    parser.add_argument("--apply", action="store_true", help="Execute updates against database")
    args = parser.parse_args()

    asyncio.run(retag_events(apply=args.apply))
