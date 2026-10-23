"""
Audit & Export Geo-Tagger Samples and Held-Out Validation Set.

1. Exports 60 random changed events to CSV (old_country, new_country, actors, title).
2. Exports all 'Ukraine' and 'Yemen' tagged events to CSV.
3. Extracts 50 unseen real headlines from the database for out-of-sample validation.

Usage:
    python scripts/audit_and_export_samples.py
"""

import asyncio
import csv
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from core.database import AsyncSessionFactory
from modules.events.models import Event
from workers.geo_tagger import extract_countries, strip_publisher_suffix


async def audit_and_export():
    async with AsyncSessionFactory() as session:
        res = await session.execute(
            select(Event.id, Event.title, Event.description, Event.source, Event.country)
            .order_by(Event.created_at.desc())
        )
        events = res.fetchall()

    print(f"Total events in database: {len(events)}")

    changed_rows = []
    ukraine_rows = []
    yemen_rows = []

    for eid, title, desc, source, old_country in events:
        new_primary, secondary = extract_countries(
            title=title or "",
            body=desc or "",
            source=source,
        )
        resolved_country = new_primary or "Unknown"

        row_dict = {
            "id": str(eid)[:8],
            "old_country": old_country or "Unknown",
            "new_country": resolved_country,
            "actors": ", ".join(secondary),
            "title": strip_publisher_suffix(title or "", source)[:90],
        }

        if resolved_country != (old_country or "Unknown"):
            changed_rows.append(row_dict)

        if resolved_country == "Ukraine":
            ukraine_rows.append(row_dict)
        elif resolved_country == "Yemen":
            yemen_rows.append(row_dict)

    print(f"Changed rows: {len(changed_rows)}")
    print(f"Total Ukraine rows: {len(ukraine_rows)}")
    print(f"Total Yemen rows: {len(yemen_rows)}")

    # 1. Export 60 random changed rows
    random.seed(42)
    sample_60 = random.sample(changed_rows, min(60, len(changed_rows)))

    os.makedirs("audit_samples", exist_ok=True)

    with open("audit_samples/changed_sample_60.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "old_country", "new_country", "actors", "title"])
        writer.writeheader()
        writer.writerows(sample_60)

    # 2. Export Ukraine & Yemen rows
    with open("audit_samples/ukraine_events.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "old_country", "new_country", "actors", "title"])
        writer.writeheader()
        writer.writerows(ukraine_rows)

    with open("audit_samples/yemen_events.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "old_country", "new_country", "actors", "title"])
        writer.writeheader()
        writer.writerows(yemen_rows)

    # 3. Pull 50 held-out headlines from database (distinct from the 30 regression cases)
    # Pick every 15th event to ensure broad historical spread across topics
    held_out_50 = []
    for i in range(0, min(len(events), 50 * 15), 15):
        if len(held_out_50) >= 50:
            break
        eid, title, desc, source, old_country = events[i]
        new_primary, secondary = extract_countries(title=title or "", body=desc or "", source=source)
        held_out_50.append({
            "id": str(eid)[:8],
            "title": strip_publisher_suffix(title or "", source)[:90],
            "source": source or "",
            "old_country": old_country or "Unknown",
            "extracted_country": new_primary or "Unknown",
            "actors": ", ".join(secondary),
        })

    with open("audit_samples/held_out_50_headlines.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "source", "old_country", "extracted_country", "actors"])
        writer.writeheader()
        writer.writerows(held_out_50)

    print("Successfully exported all audit files to audit_samples/ directory.")


if __name__ == "__main__":
    asyncio.run(audit_and_export())
