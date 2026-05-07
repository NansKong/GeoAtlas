import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Date
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from core.database import Base


class KGEntity(Base):
    """Knowledge Graph node — can be an ASSET, SECTOR, COUNTRY, or COMMODITY."""
    __tablename__ = "kg_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # ASSET | SECTOR | COUNTRY | COMMODITY
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class KGRelationship(Base):
    """Knowledge Graph edge — directional relationship between two entities."""
    __tablename__ = "kg_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Relationship types: SUPPLIES_TO | COMPETES_WITH | PART_OF | CORRELATED | REGULATES
    relationship: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    strength: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0.0 - 1.0
    data_source: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)  # MANUAL | SEC_FILING | ML_DERIVED
    last_verified: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
