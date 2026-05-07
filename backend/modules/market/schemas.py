import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AssetOut(BaseModel):
    id: uuid.UUID
    ticker: str
    name: str
    asset_type: str
    sector: Optional[str]
    industry: Optional[str]
    country: Optional[str]
    exchange: Optional[str]
    currency: str

    model_config = {"from_attributes": True}


class QuoteOut(BaseModel):
    ticker: str
    price: float
    currency: str
    as_of: datetime
    source: str
    cache_hit: bool


class OHLCVPointOut(BaseModel):
    timestamp: datetime
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    volume: Optional[float]


class OHLCVOut(BaseModel):
    ticker: str
    interval: str
    points: list[OHLCVPointOut]
    source: str
    cache_hit: bool


class FundamentalsOut(BaseModel):
    ticker: str
    currency: str
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    eps: Optional[float]
    dividend_yield: Optional[float]
    week_52_high: Optional[float]
    week_52_low: Optional[float]
    as_of: datetime
    source: str
    cache_hit: bool


class WatchlistCreateIn(BaseModel):
    asset_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None


class WatchlistLatestImpactOut(BaseModel):
    event_id: uuid.UUID
    event_title: str
    event_type: str
    impact_direction: str
    impact_strength: Optional[float] = None
    confidence_score: Optional[float] = None
    published_at: Optional[datetime] = None


class WatchlistItemOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    asset_id: uuid.UUID
    created_at: datetime
    asset: AssetOut
    latest_impact: Optional[WatchlistLatestImpactOut] = None

    model_config = {"from_attributes": True}
