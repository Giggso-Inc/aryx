"""
Subscription-plan response/list/filter schemas.

Split out of the former app/schemas/subscription_plan.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Any, List, Optional
from pydantic import BaseModel, validator
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from .base import SubscriptionPlanBase


class SubscriptionPlanResponse(SubscriptionPlanBase):
    """Schema for subscription plan responses."""
    id: UUID
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @validator('plan_cycles', pre=True)
    def ensure_positive_plan_cycles(cls, value) -> int:
        """
        Handle legacy records that may contain zero or negative plan_cycles.
        Coerce such values to 1 so that the response remains valid.
        """
        if value is None:
            return 1
        try:
            if int(value) < 1:
                return 1
        except (TypeError, ValueError):
            return 1
        return value

    class Config:
        from_attributes = True


class SubscriptionPlanPublicResponse(BaseModel):
    """Public response schema for subscription plans (more permissive for legacy data)."""
    id: UUID
    name: str
    plan_code: str
    description: Optional[str] = None
    monthly_price: Decimal
    plan_cycles: int  # No validation constraint to handle legacy data
    interval: int
    interval_unit: str
    interval_count: int
    features: Optional[Any] = None
    sort_order: int
    is_active: bool
    zoho_plan_id: Optional[str] = None
    zoho_product_id: Optional[str] = None
    zoho_plan_code: Optional[str] = None
    zoho_product_code: Optional[str] = None
    zoho_billing_cycle: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionPlanList(BaseModel):
    """Schema for subscription plan list responses."""
    plans: List[SubscriptionPlanResponse]
    total: int
    page: int
    size: int


class SubscriptionPlanFilter(BaseModel):
    """Schema for filtering subscription plans."""
    name: Optional[str] = None
    plan_code: Optional[str] = None
    is_active: Optional[bool] = None
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
