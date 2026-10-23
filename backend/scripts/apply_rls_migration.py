"""
GeoAtlas — Apply Row Level Security (RLS) on all public tables in Supabase.
Resolves Supabase Security Advisor finding: 0013_rls_disabled_in_public.
Updates alembic_version to 20260402_0007.
"""

import asyncio
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import engine
from sqlalchemy import text

PUBLIC_TABLES = [
    "alembic_version",
    "alert_notifications",
    "alerts",
    "assets",
    "boards",
    "event_articles",
    "event_impacts",
    "event_review_actions",
    "event_tags",
    "event_training_examples",
    "events",
    "institutional_api_keys",
    "kg_entities",
    "kg_relationships",
    "market_prices",
    "news_articles",
    "pins",
    "predictions",
    "users",
    "watchlists",
]

NEW_ALEMBIC_VERSION = "20260402_0007"
PREV_ALEMBIC_VERSION = "20260401_0006"


async def apply_rls():
    print("=" * 60)
    print("GeoAtlas RLS Security Migration")
    print("=" * 60)

    async with engine.begin() as conn:
        # 1. Verify current alembic_version
        res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
        current_version = res.scalar()
        print(f"[*] Current alembic_version in DB: {current_version}")

        # 2. Enable RLS on all 20 tables
        print("\n[*] Enabling Row Level Security on public tables...")
        for table in PUBLIC_TABLES:
            await conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;'))
            print(f"  [+] ALTER TABLE \"{table}\" ENABLE ROW LEVEL SECURITY; -> OK")

        # 3. Update alembic_version
        if current_version == PREV_ALEMBIC_VERSION:
            await conn.execute(
                text("UPDATE alembic_version SET version_num = :new_ver WHERE version_num = :prev_ver;"),
                {"new_ver": NEW_ALEMBIC_VERSION, "prev_ver": PREV_ALEMBIC_VERSION},
            )
            print(f"\n[*] Updated alembic_version: {PREV_ALEMBIC_VERSION} -> {NEW_ALEMBIC_VERSION}")
        elif current_version is None:
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:new_ver);"),
                {"new_ver": NEW_ALEMBIC_VERSION},
            )
            print(f"\n[*] Inserted alembic_version: {NEW_ALEMBIC_VERSION}")
        else:
            print(f"\n[!] Note: alembic_version was {current_version}, leaving revision as-is or updating to {NEW_ALEMBIC_VERSION}")
            await conn.execute(
                text("UPDATE alembic_version SET version_num = :new_ver;"),
                {"new_ver": NEW_ALEMBIC_VERSION},
            )

    # 4. Verify relrowsecurity status
    print("\n[*] Verifying pg_class relrowsecurity status across all public tables...")
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT c.relname, c.relrowsecurity 
            FROM pg_class c 
            JOIN pg_namespace n ON n.oid = c.relnamespace 
            WHERE c.relkind = 'r' AND n.nspname = 'public' 
            ORDER BY c.relname;
        """))
        rows = res.fetchall()
        all_secure = True
        for name, rls in rows:
            status = "SECURED (RLS Active)" if rls else "UNSECURED"
            if not rls:
                all_secure = False
            print(f"  {name:30} -> {status}")

        print("\n" + ("=" * 60))
        if all_secure:
            print("[SUCCESS] All 20 tables have Row Level Security enabled!")
            print("Supabase linter finding '0013_rls_disabled_in_public' is resolved.")
        else:
            print("[WARNING] Some tables still have RLS disabled.")
        print("=" * 60)

        # 5. Sanity check: Ensure backend connection queries execute normally
        print("\n[*] Running health check query on key tables via backend engine...")
        counts = {}
        for test_table in ["assets", "events", "users", "market_prices"]:
            cnt_res = await conn.execute(text(f'SELECT COUNT(*) FROM "{test_table}";'))
            counts[test_table] = cnt_res.scalar()
        print(f"[*] Backend read counts: {counts}")
        print("[SUCCESS] Backend queries executed smoothly without restriction.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(apply_rls())
