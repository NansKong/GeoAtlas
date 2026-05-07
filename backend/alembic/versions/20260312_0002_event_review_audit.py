"""event review audit trail

Revision ID: 20260312_0002
Revises: 20260312_0001
Create Date: 2026-03-12 05:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260312_0002"
down_revision: Union[str, None] = "20260312_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before_status", sa.String(length=32), nullable=True),
        sa.Column("after_status", sa.String(length=32), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_review_actions_action", "event_review_actions", ["action"], unique=False)
    op.create_index("ix_event_review_actions_created_at", "event_review_actions", ["created_at"], unique=False)
    op.create_index("ix_event_review_actions_event_id", "event_review_actions", ["event_id"], unique=False)
    op.create_index("ix_event_review_actions_reviewer_id", "event_review_actions", ["reviewer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_event_review_actions_reviewer_id", table_name="event_review_actions")
    op.drop_index("ix_event_review_actions_event_id", table_name="event_review_actions")
    op.drop_index("ix_event_review_actions_created_at", table_name="event_review_actions")
    op.drop_index("ix_event_review_actions_action", table_name="event_review_actions")
    op.drop_table("event_review_actions")
