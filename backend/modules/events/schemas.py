import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class NewsArticleOut(BaseModel):
    id: uuid.UUID
    title: str
    source: str
    url: str
    published_at: Optional[datetime]
    sentiment_score: Optional[float]
    language_code: Optional[str] = None
    language_confidence: Optional[float] = None
    relevance_score: Optional[float] = None
    relevance_label: Optional[str] = None
    nlp_processed_at: Optional[datetime] = None
    snippet: Optional[str] = None
    category: str = "general"
    matched_event_type: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventImpactOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    impact_direction: str
    impact_strength: Optional[float]
    confidence_score: Optional[float]
    ticker: Optional[str] = None
    name: Optional[str] = None

    model_config = {"from_attributes": True}


class AffectedAssetOut(BaseModel):
    ticker: str
    name: Optional[str] = None
    impact_direction: str
    impact_strength: Optional[float] = None
    confidence_score: Optional[float] = None


class EventOut(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str]
    event_type: str
    country: Optional[str]
    region: Optional[str]
    severity: Optional[int]
    status: str
    confidence_score: Optional[float]
    published_at: Optional[datetime]
    created_at: datetime
    tags: List[str] = []
    impacts: List[EventImpactOut] = []

    model_config = {"from_attributes": True}


class EventListOut(BaseModel):
    id: uuid.UUID
    title: str
    event_type: str
    country: Optional[str]
    severity: Optional[int]
    confidence_score: Optional[float]
    published_at: Optional[datetime]
    impact_count: int = 0
    affected_assets: List[AffectedAssetOut] = []
    tags: List[str] = []

    model_config = {"from_attributes": True}


class EventHeatmapPointOut(BaseModel):
    country: str
    event_count: int
    avg_severity: float
    avg_confidence: float
    conflict_share: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class QualitySummaryOut(BaseModel):
    classification_accuracy: Optional[float] = None
    nlp_latency_p95_seconds: Optional[float] = None
    auto_approved_rate: Optional[float] = None
    review_queue_backlog: int = 0
    news_ingestion_freshness_minutes: Optional[float] = None
    asset_mapping_coverage: Optional[float] = None


class WeeklyReviewProgressOut(BaseModel):
    week_start_utc: datetime
    week_end_utc: datetime
    reviewed_events: int
    target_min: int = 50
    target_max: int = 100
    target_met: bool


class ReviewArticleOut(BaseModel):
    id: uuid.UUID
    title: str
    source: str
    url: str
    published_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EventReviewOut(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str]
    event_type: str
    country: Optional[str]
    region: Optional[str]
    severity: Optional[int]
    status: str
    confidence_score: Optional[float]
    published_at: Optional[datetime]
    created_at: datetime
    articles: List[ReviewArticleOut] = []
    tags: List[str] = []
    affected_assets: List[AffectedAssetOut] = []

    model_config = {"from_attributes": True}


class ReviewDecisionIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    severity: Optional[int] = None
    confidence_score: Optional[float] = None


class ReviewActionOut(BaseModel):
    id: uuid.UUID
    status: str
    message: str


class ReviewHistoryOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    reviewer_id: uuid.UUID
    action: str
    before_status: Optional[str]
    after_status: Optional[str]
    changes: Optional[dict]
    note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingExampleOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    article_id: uuid.UUID
    reviewer_id: uuid.UUID
    review_action: str
    label_event_type: Optional[str]
    label_status: str
    language_code: Optional[str]
    title: str
    article_title: str
    article_content: Optional[str]
    source: Optional[str]
    url: Optional[str]
    country: Optional[str]
    region: Optional[str]
    severity: Optional[int]
    confidence_score: Optional[float]
    tags: List[str] = []
    affected_assets: List[dict] = []
    metadata_: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}
