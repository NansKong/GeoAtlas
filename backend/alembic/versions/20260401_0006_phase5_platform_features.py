"""phase 5 platform features

Revision ID: 20260401_0006
Revises: 20260401_0005
Create Date: 2026-04-01 20:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260401_0006"
down_revision: Union[str, None] = "20260401_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pins", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY board_id ORDER BY created_at ASC, id ASC) - 1 AS new_position
            FROM pins
        )
        UPDATE pins
        SET position = ranked.new_position
        FROM ranked
        WHERE pins.id = ranked.id
        """
    )
    op.alter_column("pins", "position", server_default=None)

    op.add_column("users", sa.Column("stripe_customer_id", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True))
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=False)
    op.create_index("ix_users_stripe_subscription_id", "users", ["stripe_subscription_id"], unique=False)

    op.create_table(
        "institutional_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_institutional_api_keys_user_id", "institutional_api_keys", ["user_id"], unique=False)
    op.create_index("ix_institutional_api_keys_key_prefix", "institutional_api_keys", ["key_prefix"], unique=False)
    op.create_index("ix_institutional_api_keys_key_hash", "institutional_api_keys", ["key_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_institutional_api_keys_key_hash", table_name="institutional_api_keys")
    op.drop_index("ix_institutional_api_keys_key_prefix", table_name="institutional_api_keys")
    op.drop_index("ix_institutional_api_keys_user_id", table_name="institutional_api_keys")
    op.drop_table("institutional_api_keys")

    op.drop_index("ix_users_stripe_subscription_id", table_name="users")
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")

    op.drop_column("pins", "position")
