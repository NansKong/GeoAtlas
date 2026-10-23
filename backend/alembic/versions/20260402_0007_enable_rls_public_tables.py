"""enable row level security on public tables

Revision ID: 20260402_0007
Revises: 20260401_0006
Create Date: 2026-09-23 01:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260402_0007"
down_revision: Union[str, None] = "20260401_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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


def upgrade() -> None:
    for table in PUBLIC_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    for table in PUBLIC_TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')
