"""initial schema

Revision ID: 20260312_0001
Revises:
Create Date: 2026-03-12 03:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from core.database import Base

# Import all models so Base.metadata contains the full schema.
from modules.users.models import User  # noqa: F401
from modules.market.models import Asset, MarketPrice, Watchlist  # noqa: F401
from modules.events.models import Event, EventArticle, EventImpact, EventTag, NewsArticle  # noqa: F401
from modules.predictions.models import Prediction  # noqa: F401
from modules.boards.models import Alert, Board, Pin  # noqa: F401
from modules.knowledge_graph.models import KGEntity, KGRelationship  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "20260312_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUM_TYPES = [
    "userrole",
    "assettype",
    "eventtype",
    "impactdirection",
    "eventstatus",
    "predictionhorizon",
    "predictiondirection",
    "predictionoutcome",
    "boardvisibility",
    "pincontenttype",
]

BASE_TABLE_NAMES = [
    "users",
    "assets",
    "news_articles",
    "events",
    "event_tags",
    "event_articles",
    "event_impacts",
    "predictions",
    "boards",
    "pins",
    "watchlists",
    "alerts",
    "kg_entities",
    "kg_relationships",
    "market_prices",
]


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in BASE_TABLE_NAMES]
    Base.metadata.create_all(bind=bind, tables=tables)

    # Required composite index from requirements/task checklist.
    op.create_index(
        "ix_market_prices_asset_id_timestamp",
        "market_prices",
        ["asset_id", "timestamp"],
        unique=False,
    )

    # Best effort Timescale conversion when available.
    op.execute(
        """
        DO $$
        BEGIN
            BEGIN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
            EXCEPTION
                WHEN insufficient_privilege THEN
                    RAISE NOTICE 'timescaledb extension not created due to insufficient privilege';
                WHEN feature_not_supported THEN
                    RAISE NOTICE 'timescaledb extension not available on this Postgres build';
                WHEN undefined_file THEN
                    RAISE NOTICE 'timescaledb extension files not installed on this server';
            END;

            IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
                PERFORM create_hypertable('market_prices', 'timestamp', if_not_exists => TRUE);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_market_prices_asset_id_timestamp", table_name="market_prices")
    tables = [Base.metadata.tables[name] for name in BASE_TABLE_NAMES]
    Base.metadata.drop_all(bind=bind, tables=tables)

    # SQLAlchemy does not always drop PG enum types on drop_all.
    for enum_name in ENUM_TYPES:
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)

