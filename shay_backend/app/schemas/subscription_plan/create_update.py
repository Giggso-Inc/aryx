"""
Subscription-plan create/update request schemas.

Split out of the former app/schemas/subscription_plan.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator
from decimal import Decimal

from .base import SubscriptionPlanBase


class SubscriptionPlanCreate(SubscriptionPlanBase):
    """Schema for creating a new subscription plan."""
    pass


class SubscriptionPlanUpdate(BaseModel):
    """Schema for updating a subscription plan."""
    name: Optional[str] = Field(None, description="Plan name", min_length=1, max_length=255)
    plan_code: Optional[str] = Field(None, description="Unique plan code", min_length=1, max_length=50)
    description: Optional[str] = Field(None, description="Plan description")
    monthly_price: Optional[Decimal] = Field(None, description="Monthly price", ge=0)
    plan_cycles: Optional[int] = Field(None, description="Number of plan cycles", ge=1)

    # Billing configuration
    interval: Optional[int] = Field(None, description="Billing interval", ge=1)
    interval_unit: Optional[str] = Field(None, description="Billing interval unit", max_length=20)
    interval_count: Optional[int] = Field(None, description="Number of intervals", ge=1)

    # Features and metadata
    features: Optional[Any] = Field(None, description="Plan features (dictionary or list)")
    sort_order: Optional[int] = Field(None, description="Sort order for display")
    is_active: Optional[bool] = Field(None, description="Whether the plan is active")

    @validator('features')
    def validate_features(cls, v) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        # If features is a list, convert it to a dictionary with numbered keys
        if isinstance(v, list):
            return {f"feature_{i+1}": feature for i, feature in enumerate(v)}
        # If it's already a dictionary, return as is
        elif isinstance(v, dict):
            return v
        else:
            raise ValueError('Features must be a dictionary or list')

    # Zoho integration fields
    zoho_plan_id: Optional[str] = Field(None, description="Zoho plan ID", max_length=255)
    zoho_product_id: Optional[str] = Field(None, description="Zoho product ID", max_length=255)
    zoho_plan_code: Optional[str] = Field(None, description="Zoho plan code", max_length=255)
    zoho_product_code: Optional[str] = Field(None, description="Zoho product code", max_length=255)
    zoho_billing_cycle: Optional[str] = Field(None, description="Zoho billing cycle", max_length=50)

    # Platform configuration
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). Used for Zoho configuration selection")

    @validator('interval_unit')
    def validate_interval_unit(cls, v) -> Optional[str]:
        if v is not None:
            # Accept both singular and plural forms
            v_lower = v.lower()
            # Handle common plural forms
            if v_lower.endswith('s'):
                v_singular = v_lower[:-1]
            else:
                v_singular = v_lower

            allowed_units = ['month', 'year', 'week', 'day']
            if v_singular not in allowed_units:
                raise ValueError(f'Interval unit must be one of: {allowed_units} (singular or plural)')
            # Return the original value to preserve user's input
            return v
        return v
