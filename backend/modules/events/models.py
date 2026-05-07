import uuid
import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    String, Text, Float, DateTime, ForeignKey,
    Enum as SAEnum, Integer, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from core.database import Base


class EventType(str, enum.Enum):
    CONFLICT = "conflict"
    SANCTION = "sanction"
    TRADE_POLICY = "trade_policy"
    ECONOMIC_DATA = "economic_data"
    ENERGY_DISRUPTION = "energy_disruption"
    ELECTION = "election"
    REGULATION = "regulation"


class ImpactDirection(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class EventStatus(str, enum.Enum):
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    HUMAN_APPROVED = "human_approved"


# ─── News Article ────────────────────────────────────────────────────────────

class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    language_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    relevance_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    nlp_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ─── Event ───────────────────────────────────────────────────────────────────

class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_type: Mapped[EventType] = mapped_column(SAEnum(EventType), nullable=False, index=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    severity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus), default=EventStatus.PENDING_REVIEW, nullable=False
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    tags: Mapped[list["EventTag"]] = relationship("EventTag", back_populates="event", cascade="all, delete-orphan")
    impacts: Mapped[list["EventImpact"]] = relationship("EventImpact", back_populates="event", cascade="all, delete-orphan")
    articles: Mapped[list["EventArticle"]] = relationship("EventArticle", back_populates="event", cascade="all, delete-orphan")


# ─── Event Tag ───────────────────────────────────────────────────────────────

class EventTag(Base):
    __tablename__ = "event_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)

    event: Mapped["Event"] = relationship("Event", back_populates="tags")

    __table_args__ = (UniqueConstraint("event_id", "tag", name="uq_event_tag"),)


# ─── Event Impact ─────────────────────────────────────────────────────────────

class EventImpact(Base):
    __tablename__ = "event_impacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    impact_direction: Mapped[ImpactDirection] = mapped_column(SAEnum(ImpactDirection), nullable=False)
    impact_strength: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0.0 - 1.0
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # filled post-event
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    event: Mapped["Event"] = relationship("Event", back_populates="impacts")


# ─── Event Article Mapping ────────────────────────────────────────────────────

class EventArticle(Base):
    __tablename__ = "event_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    event: Mapped["Event"] = relationship("Event", back_populates="articles")


class EventReviewAction(Base):
    __tablename__ = "event_review_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # edit|approve|reject
    before_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    after_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    changes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class EventTrainingExample(Base):
    __tablename__ = "event_training_examples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    label_event_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    label_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    article_title: Mapped[str] = mapped_column(String(500), nullable=False)
    article_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    severity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    affected_assets: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint("event_id", "article_id", "review_action", name="uq_training_example_event_article_action"),
        Index("ix_training_examples_event_type_status", "label_event_type", "label_status"),
    )
