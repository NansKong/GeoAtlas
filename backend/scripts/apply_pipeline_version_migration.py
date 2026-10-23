"""
Apply pipeline_version and country_legacy columns to events and event_impacts.

Usage:
    python scripts/apply_pipeline_version_migration.py --dry-run
    python scripts/apply_pipeline_version_migration.py --apply
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from core.database import AsyncSessionFactory


async def run_migration(apply: bool = False):
    print(f"\n{'='*70}")
    print(f"DATABASE SCHEMA MIGRATION: pipeline_version & country_legacy")
    print(f"MODE: {'APPLY (COMMITTING CHANGES)' if apply else 'DRY RUN (NO CHANGES WRITTEN)'}")
    print(f"{'='*70}\n")

    async with AsyncSessionFactory() as session:
        # Check existing columns in events
        check_events = await session.execute(
            text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'events' AND column_name IN ('country_legacy', 'pipeline_version');
            """)
        )
        existing_event_cols = {row[0] for row in check_events.fetchall()}

        # Check existing columns in event_impacts
        check_impacts = await session.execute(
            text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'event_impacts'
            AND column_name IN ('pipeline_version', 'is_superseded', 'rationale', 'magnitude');
            """)
        )
        existing_impact_cols = {row[0] for row in check_impacts.fetchall()}

        print(f"Existing in 'events': {existing_event_cols or 'None'}")
        print(f"Existing in 'event_impacts': {existing_impact_cols or 'None'}\n")

        # Planned statements
        ddl_statements = []

        if "country_legacy" not in existing_event_cols:
            ddl_statements.append("ALTER TABLE events ADD COLUMN country_legacy VARCHAR(100);")
        if "pipeline_version" not in existing_event_cols:
            ddl_statements.append("ALTER TABLE events ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1;")

        if "pipeline_version" not in existing_impact_cols:
            ddl_statements.append("ALTER TABLE event_impacts ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1;")
        if "is_superseded" not in existing_impact_cols:
            ddl_statements.append("ALTER TABLE event_impacts ADD COLUMN is_superseded BOOLEAN NOT NULL DEFAULT false;")
        if "rationale" not in existing_impact_cols:
            ddl_statements.append("ALTER TABLE event_impacts ADD COLUMN rationale VARCHAR(500);")
        if "magnitude" not in existing_impact_cols:
            ddl_statements.append("ALTER TABLE event_impacts ADD COLUMN magnitude VARCHAR(32);")

        if not ddl_statements:
            print("All schema columns already exist. Database is up to date!")
            return

        print("Planned DDL Operations:")
        for stmt in ddl_statements:
            print(f"  [DDL] {stmt}")

        if not apply:
            print("\nDRY RUN complete. Re-run with --apply to execute these statements in a transaction.")
            return

        # Execute inside a transaction
        print("\nExecuting DDL statements...")
        async with session.begin():
            for stmt in ddl_statements:
                await session.execute(text(stmt))
                print(f"  EXECUTED: {stmt}")

            # Update alembic_version if table exists
            has_alembic = (await session.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version';")
            )).scalar()
            if has_alembic:
                await session.execute(text("UPDATE alembic_version SET version_num = '20260403_0008';"))
                print("  UPDATED alembic_version -> 20260403_0008")

        print("\nSUCCESS: All schema modifications successfully applied.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migration runner with dry-run support")
    parser.add_argument("--apply", action="store_true", help="Execute DDL statements against the database")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without applying (default)")
    args = parser.parse_args()

    asyncio.run(run_migration(apply=args.apply))
