"""event training examples

Revision ID: 20260313_0004
Revises: 20260313_0003
Create Date: 2026-03-13 04:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260313_0004"
down_revision: Union[str, None] = "20260313_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_training_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_action", sa.String(length=20), nullable=False),
        sa.Column("label_event_type", sa.String(length=32), nullable=True),
        sa.Column("label_status", sa.String(length=32), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("article_title", sa.String(length=500), nullable=False),
        sa.Column("article_content", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("affected_assets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "article_id", "review_action", name="uq_training_example_event_article_action"),
    )
    op.create_index("ix_event_training_examples_event_id", "event_training_examples", ["event_id"], unique=False)
    op.create_index("ix_event_training_examples_article_id", "event_training_examples", ["article_id"], unique=False)
    op.create_index("ix_event_training_examples_reviewer_id", "event_training_examples", ["reviewer_id"], unique=False)
    op.create_index("ix_event_training_examples_review_action", "event_training_examples", ["review_action"], unique=False)
    op.create_index("ix_event_training_examples_label_event_type", "event_training_examples", ["label_event_type"], unique=False)
    op.create_index("ix_event_training_examples_label_status", "event_training_examples", ["label_status"], unique=False)
    op.create_index("ix_event_training_examples_language_code", "event_training_examples", ["language_code"], unique=False)
    op.create_index("ix_event_training_examples_created_at", "event_training_examples", ["created_at"], unique=False)
    op.create_index(
        "ix_training_examples_event_type_status",
        "event_training_examples",
        ["label_event_type", "label_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_training_examples_event_type_status", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_created_at", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_language_code", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_label_status", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_label_event_type", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_review_action", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_reviewer_id", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_article_id", table_name="event_training_examples")
    op.drop_index("ix_event_training_examples_event_id", table_name="event_training_examples")
    op.drop_table("event_training_examples")
