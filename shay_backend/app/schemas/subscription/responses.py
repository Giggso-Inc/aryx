"""
Subscription response/list/filter schemas.

Split out of the former app/schemas/subscription.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from .base import SubscriptionBase


class SubscriptionResponse(SubscriptionBase):
    """Schema for subscription response."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubscriptionList(BaseModel):
    """Schema for subscription list response."""
    subscriptions: List[SubscriptionResponse]
    total: int
    page: int
    size: int


class SubscriptionFilter(BaseModel):
    """Schema for filtering subscriptions."""
    company_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    status: Optional[str] = None
    subscription_status: Optional[str] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    billing_cycle: Optional[str] = None


class CompanyCurrentPlanResponse(BaseModel):
    """Schema for company's current plan details."""
    plan_name: str = Field(..., description="Current plan name")
    plan_code: str = Field(..., description="Current plan code")
    billing_cycle: str = Field(..., description="Billing cycle")
    cost: Decimal = Field(..., description="Plan cost")
    currency_code: str = Field(..., description="Currency code")
    next_renewal: datetime = Field(..., description="Next renewal date")
    status: str = Field(..., description="Subscription status")
    features: Optional[Dict[str, Any]] = Field(None, description="Plan features")
    current_period_start: datetime = Field(..., description="Current period start")
    current_period_end: datetime = Field(..., description="Current period end")
    is_trial: bool = Field(..., description="Whether currently in trial period")
    trial_end: Optional[datetime] = Field(None, description="Trial end date if applicable")

    @field_validator('features', mode='before')
    @classmethod
    def validate_features(cls, v) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        if isinstance(v, list):
            return {f"feature_{i+1}": feature for i, feature in enumerate(v)}
        elif isinstance(v, dict):
            return v
        else:
            raise ValueError('Features must be a dictionary or list')

    class Config:
        from_attributes = True
