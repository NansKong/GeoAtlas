"""news article nlp metadata

Revision ID: 20260313_0003
Revises: 20260312_0002
Create Date: 2026-03-13 02:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260313_0003"
down_revision: Union[str, None] = "20260312_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("news_articles")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("news_articles")}

    if "language_code" not in existing_columns:
        op.add_column("news_articles", sa.Column("language_code", sa.String(length=16), nullable=True))
    if "language_confidence" not in existing_columns:
        op.add_column("news_articles", sa.Column("language_confidence", sa.Float(), nullable=True))
    if "relevance_score" not in existing_columns:
        op.add_column("news_articles", sa.Column("relevance_score", sa.Float(), nullable=True))
    if "relevance_label" not in existing_columns:
        op.add_column("news_articles", sa.Column("relevance_label", sa.String(length=32), nullable=True))
    if "nlp_processed_at" not in existing_columns:
        op.add_column("news_articles", sa.Column("nlp_processed_at", sa.DateTime(timezone=True), nullable=True))

    if "ix_news_articles_language_code" not in existing_indexes:
        op.create_index("ix_news_articles_language_code", "news_articles", ["language_code"], unique=False)
    if "ix_news_articles_relevance_score" not in existing_indexes:
        op.create_index("ix_news_articles_relevance_score", "news_articles", ["relevance_score"], unique=False)
    if "ix_news_articles_relevance_label" not in existing_indexes:
        op.create_index("ix_news_articles_relevance_label", "news_articles", ["relevance_label"], unique=False)
    if "ix_news_articles_nlp_processed_at" not in existing_indexes:
        op.create_index("ix_news_articles_nlp_processed_at", "news_articles", ["nlp_processed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_news_articles_nlp_processed_at", table_name="news_articles")
    op.drop_index("ix_news_articles_relevance_label", table_name="news_articles")
    op.drop_index("ix_news_articles_relevance_score", table_name="news_articles")
    op.drop_index("ix_news_articles_language_code", table_name="news_articles")

    op.drop_column("news_articles", "nlp_processed_at")
    op.drop_column("news_articles", "relevance_label")
    op.drop_column("news_articles", "relevance_score")
    op.drop_column("news_articles", "language_confidence")
    op.drop_column("news_articles", "language_code")
