import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    username: str = Field(min_length=3, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    role: str
    subscription_plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertPreferencesOut(BaseModel):
    email_enabled: bool = True
    web_push_enabled: bool = False
    web_push_tokens: list[str] = []
    email_delivery_ready: bool = False
    web_push_delivery_ready: bool = False


class AlertPreferencesUpdate(BaseModel):
    email_enabled: Optional[bool] = None
    web_push_enabled: Optional[bool] = None
    web_push_tokens: Optional[list[str]] = None


class BillingPlanOut(BaseModel):
    id: str
    name: str
    price_monthly: Optional[int] = None
    currency: str = "usd"
    features: list[str]


class BillingLimitsOut(BaseModel):
    subscription_plan: str
    boards_used: int
    boards_limit: Optional[int] = None
    alerts_used: int
    alerts_limit: Optional[int] = None
    predictions_remaining_today: Optional[int] = None
    predictions_daily_limit: Optional[int] = None
    stripe_configured: bool = False
    institutional_api_enabled: bool = False


class BillingCheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(pro|institutional)$")


class BillingSessionOut(BaseModel):
    url: str


class SubscriptionPlanUpdate(BaseModel):
    subscription_plan: str = Field(pattern="^(free|pro|institutional)$")


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreateOut(ApiKeyOut):
    api_key: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
