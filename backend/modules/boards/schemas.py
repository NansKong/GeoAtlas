import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BoardCreate(BaseModel):
    title: str
    description: Optional[str] = None
    visibility: str = "private"
    cover_image_url: Optional[str] = None


class BoardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    cover_image_url: Optional[str] = None


class BoardOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: Optional[str]
    visibility: str
    cover_image_url: Optional[str]
    created_at: datetime
    pin_count: int = 0

    model_config = {"from_attributes": True}


class PinCreate(BaseModel):
    board_id: Optional[uuid.UUID] = None
    content_type: str  # event | asset | prediction | news
    content_id: uuid.UUID
    note: Optional[str] = None
    position: Optional[int] = None


class PinUpdate(BaseModel):
    note: Optional[str] = None
    position: Optional[int] = None


class PinReorderIn(BaseModel):
    pin_ids: List[uuid.UUID]


class PinOut(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    content_type: str
    content_id: uuid.UUID
    note: Optional[str]
    position: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BoardTemplateOut(BaseModel):
    slug: str
    title: str
    description: str
    suggested_visibility: str = "private"


class AlertCreate(BaseModel):
    asset_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None
    event_type: Optional[str] = None
    threshold: Optional[float] = None
    is_active: bool = True


class AlertUpdate(BaseModel):
    asset_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None
    event_type: Optional[str] = None
    threshold: Optional[float] = None
    is_active: Optional[bool] = None


class AlertOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    asset_id: Optional[uuid.UUID]
    ticker: Optional[str] = None
    asset_name: Optional[str] = None
    event_type: Optional[str]
    threshold: Optional[float]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
