import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PredictionCreateIn(BaseModel):
    event_id: uuid.UUID
    asset_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None
    predicted_direction: str
    predicted_change_pct: Optional[float] = None
    prediction_horizon: str
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    model_version: str = Field(default="rules-v0", min_length=1, max_length=50)
    predicted_at: Optional[datetime] = None
    resolve_at: Optional[datetime] = None


class PredictionOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    asset_id: uuid.UUID
    event_title: str
    event_type: str
    ticker: str
    asset_name: Optional[str] = None
    predicted_direction: str
    predicted_change_pct: Optional[float] = None
    prediction_horizon: str
    confidence_score: Optional[float] = None
    model_version: str
    predicted_at: datetime
    resolve_at: Optional[datetime] = None
    actual_change_pct: Optional[float] = None
    outcome: str
    resolved_at: Optional[datetime] = None
    model_accuracy: Optional[float] = None
    event_type_accuracy: Optional[float] = None
    eligible_for_display: bool = False
    feature_enabled: bool = True


class PredictionSummaryOut(BaseModel):
    total_predictions: int
    resolved_predictions: int
    pending_predictions: int
    overall_accuracy: Optional[float] = None
    feature_enabled: bool = True
    display_accuracy_threshold: float = 0.60
class ConfusionMatrixOut(BaseModel):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

class AccuracyMetricsOut(BaseModel):
    overall_accuracy: Optional[float] = None
    directional_accuracy: Optional[float] = None
    mae: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    confusion_matrix: ConfusionMatrixOut = Field(default_factory=ConfusionMatrixOut)
    
    by_model_version: dict[str, float] = {}
    by_event_type: dict[str, float] = {}
    by_horizon: dict[str, float] = {}
    total_resolved: int = 0

