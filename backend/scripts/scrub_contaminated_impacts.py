"""
Impact Scrubbing and Pipeline v2 Remediation Script.

Purpose:
1. Marks legacy/contaminated event_impacts rows as is_superseded = True (preserves historical record).
2. Generates clean, directional rule-based impacts (pipeline_version = 2) for historical events
   using the verified asset_mapper.
3. Supports --dry-run (default) and --apply modes with full transactional safety.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from core.database import AsyncSessionFactory
from modules.events.models import Event, EventImpact, EventStatus
from modules.market.models import Asset
from workers.asset_mapper import map_event_to_expected_assets
from workers.entity_utils import build_asset_alias_map, extract_asset_mentions


async def scrub_impacts(apply: bool = False, limit: int = 15):
    print("\n" + "=" * 78)
    print("EVENT IMPACTS SCRUBBING & V2 RE-GENERATION")
    print(f"MODE: {'APPLY (COMMITTING WRITES TO DATABASE)' if apply else 'DRY RUN (SIMULATION ONLY - NO WRITES)'}")
    print("=" * 78 + "\n")

    async with AsyncSessionFactory() as session:
        # 1. Inspect current impacts state
        total_impacts_res = await session.execute(text("SELECT count(*) FROM event_impacts;"))
        total_impacts = total_impacts_res.scalar() or 0

        v1_impacts_res = await session.execute(
            text("SELECT count(*) FROM event_impacts WHERE is_superseded = false AND pipeline_version = 1;")
        )
        v1_active_count = v1_impacts_res.scalar() or 0

        print(f"Total event_impacts in DB: {total_impacts}")
        print(f"Active legacy (v1) impacts to supersede: {v1_active_count}\n")

        # 2. Load assets for mapping
        assets_res = await session.execute(select(Asset))
        assets = assets_res.scalars().all()
        asset_lookup = {a.ticker.upper(): a for a in assets}
        valid_tickers = set(asset_lookup.keys())
        alias_map = build_asset_alias_map(assets)

        # 3. Fetch published/approved events
        events_res = await session.execute(
            select(Event)
            .where(Event.status.in_((EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)))
            .order_by(Event.published_at.desc().nullslast(), Event.created_at.desc())
        )
        events = events_res.scalars().all()
        print(f"Total published events to evaluate: {len(events)}\n")

        new_impacts_count = 0
        samples = []

        for ev in events:
            # Direct asset mentions
            combined_text = f"{ev.title}\n{ev.description or ''}"
            direct_tickers = extract_asset_mentions(combined_text, valid_tickers, alias_map)

            # Rule-based expected impacts
            expected = map_event_to_expected_assets(
                event_type=ev.event_type,
                title=ev.title,
                country=ev.country,
                valid_tickers=valid_tickers,
            )

            event_new_count = len(direct_tickers) + len(expected)
            new_impacts_count += event_new_count

            if len(samples) < limit and (expected or direct_tickers):
                samples.append({
                    "id": str(ev.id)[:8],
                    "title": ev.title[:65],
                    "country": ev.country or "Global",
                    "type": ev.event_type.value,
                    "expected": [f"{imp.ticker}({imp.direction.value[:3]})" for imp in expected[:5]],
                    "direct": direct_tickers[:3],
                })

        print("--- SAMPLE RE-MAPPED EVENT IMPACTS ---")
        for s in samples:
            exp_str = ", ".join(s["expected"]) if s["expected"] else "none"
            dir_str = f" [direct: {', '.join(s['direct'])}]" if s["direct"] else ""
            print(f"[{s['id']}] [{s['type']:<15}] [{s['country']:<12}] -> {exp_str}{dir_str}")
            print(f"      Title: {s['title']}\n")

        print("-" * 78)
        print(f"Summary:")
        print(f"  Legacy impacts to mark is_superseded = true: {v1_active_count}")
        print(f"  Estimated clean v2 impacts to generate: ~{new_impacts_count}")

        if not apply:
            print("\n" + "=" * 78)
            print("DRY RUN COMPLETE. 0 rows modified in database.")
            print("Run with --apply to commit these changes to PostgreSQL in a transaction.")
            print("=" * 78 + "\n")
            return

        # APPLY MODE
        print("\nApplying changes to database in a transaction...")
        # Step A: Supersede all v1 impacts
        await session.execute(
            text("""
            UPDATE event_impacts
            SET is_superseded = true
            WHERE pipeline_version = 1 AND is_superseded = false;
            """)
        )

        # Step B: Insert fresh v2 impacts for each event
        inserted = 0
        for ev in events:
            combined_text = f"{ev.title}\n{ev.description or ''}"
            direct_tickers = extract_asset_mentions(combined_text, valid_tickers, alias_map)
            expected = map_event_to_expected_assets(
                event_type=ev.event_type,
                title=ev.title,
                country=ev.country,
                valid_tickers=valid_tickers,
            )

            # Direct mentions
            for ticker in direct_tickers:
                asset = asset_lookup.get(ticker)
                if not asset:
                    continue
                session.add(
                    EventImpact(
                        event_id=ev.id,
                        asset_id=asset.id,
                        impact_direction=ev.event_type and ev.event_type.value == "conflict" and "negative" or "neutral",
                        impact_strength=0.75,
                        confidence_score=0.85,
                        magnitude="high",
                        rationale="Direct asset mention in news catalyst",
                        pipeline_version=2,
                        is_superseded=False,
                    )
                )
                inserted += 1

            # Rule-based expectations
            for imp in expected:
                asset = asset_lookup.get(imp.ticker.upper())
                if not asset:
                    continue
                session.add(
                    EventImpact(
                        event_id=ev.id,
                        asset_id=asset.id,
                        impact_direction=imp.direction,
                        impact_strength=imp.strength,
                        confidence_score=0.85,
                        magnitude=imp.magnitude,
                        rationale=imp.rationale,
                        pipeline_version=2,
                        is_superseded=False,
                    )
                )
                inserted += 1

        await session.commit()
        print(f"SUCCESS: Marked {v1_active_count} legacy impacts superseded and created {inserted} clean v2 impacts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrub contaminated event impacts")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Simulate without applying")
    parser.add_argument("--apply", action="store_true", help="Execute updates against database")
    args = parser.parse_args()

    asyncio.run(scrub_impacts(apply=args.apply))
