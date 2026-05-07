"""alert notifications

Revision ID: 20260401_0005
Revises: 20260313_0004
Create Date: 2026-04-01 18:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260401_0005"
down_revision: Union[str, None] = "20260313_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", "event_id", "channel", name="uq_alert_notification_alert_event_channel"),
    )
    op.create_index("ix_alert_notifications_alert_id", "alert_notifications", ["alert_id"], unique=False)
    op.create_index("ix_alert_notifications_user_id", "alert_notifications", ["user_id"], unique=False)
    op.create_index("ix_alert_notifications_event_id", "alert_notifications", ["event_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_notifications_event_id", table_name="alert_notifications")
    op.drop_index("ix_alert_notifications_user_id", table_name="alert_notifications")
    op.drop_index("ix_alert_notifications_alert_id", table_name="alert_notifications")
    op.drop_table("alert_notifications")
