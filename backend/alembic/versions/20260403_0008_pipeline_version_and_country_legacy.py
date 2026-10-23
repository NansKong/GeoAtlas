"""add pipeline_version, country_legacy, and impact audit metadata

Revision ID: 20260403_0008
Revises: 20260402_0007
Create Date: 2026-10-22 15:30:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20260403_0008"
down_revision: Union[str, None] = "20260402_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add audit columns to events
    op.add_column("events", sa.Column("country_legacy", sa.String(length=100), nullable=True))
    op.add_column("events", sa.Column("pipeline_version", sa.Integer(), nullable=False, server_default="1"))

    # 2. Add audit and directional rationale columns to event_impacts
    op.add_column("event_impacts", sa.Column("pipeline_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("event_impacts", sa.Column("is_superseded", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("event_impacts", sa.Column("rationale", sa.String(length=500), nullable=True))
    op.add_column("event_impacts", sa.Column("magnitude", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("event_impacts", "magnitude")
    op.drop_column("event_impacts", "rationale")
    op.drop_column("event_impacts", "is_superseded")
    op.drop_column("event_impacts", "pipeline_version")
    op.drop_column("events", "pipeline_version")
    op.drop_column("events", "country_legacy")
