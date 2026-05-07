import uuid
import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base


class PredictionHorizon(str, enum.Enum):
    H1 = "1h"
    H6 = "6h"
    H24 = "24h"
    D7 = "7d"
    D30 = "30d"


class PredictionDirection(str, enum.Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class PredictionOutcome(str, enum.Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    PARTIAL = "partial"
    PENDING = "pending"


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    predicted_direction: Mapped[PredictionDirection] = mapped_column(
        SAEnum(PredictionDirection), nullable=False
    )
    predicted_change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prediction_horizon: Mapped[PredictionHorizon] = mapped_column(
        SAEnum(PredictionHorizon), nullable=False
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v0.1")
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolve_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome: Mapped[PredictionOutcome] = mapped_column(
        SAEnum(PredictionOutcome), default=PredictionOutcome.PENDING, nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
