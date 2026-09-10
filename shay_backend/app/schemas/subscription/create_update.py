"""
Subscription create/update request schemas.

Split out of the former app/schemas/subscription.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from decimal import Decimal

from .base import SubscriptionBase


class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a new subscription."""
    pass


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription."""
    status: Optional[str] = Field(None, description="Subscription status", max_length=50)
    subscription_status: Optional[str] = Field(None, description="Detailed subscription status", max_length=50)

    # Billing information
    amount: Optional[Decimal] = Field(None, description="Subscription amount", ge=0)
    currency_code: Optional[str] = Field(None, description="Currency code", max_length=3)
    billing_cycle: Optional[str] = Field(None, description="Billing cycle", max_length=50)
    auto_collect: Optional[bool] = Field(None, description="Auto-collect payments")

    # Billing periods
    current_period_start: Optional[datetime] = Field(None, description="Current period start date")
    current_period_end: Optional[datetime] = Field(None, description="Current period end date")
    next_billing_date: Optional[datetime] = Field(None, description="Next billing date")

    # Trial information
    zoho_trial_end: Optional[datetime] = Field(None, description="Trial end date")
    zoho_cancel_at_period_end: Optional[bool] = Field(None, description="Cancel at period end")

    # Usage and limits
    usage_limits: Optional[Dict[str, Any]] = Field(None, description="Usage limits and tracking")

    # Zoho integration fields
    zoho_subscription_id: Optional[str] = Field(None, description="Zoho subscription ID", max_length=255)
    zoho_customer_id: Optional[str] = Field(None, description="Zoho customer ID", max_length=255)
    zoho_hosted_page_id: Optional[str] = Field(None, description="Zoho hosted page ID", max_length=255)
    zoho_invoice_id: Optional[str] = Field(None, description="Zoho invoice ID", max_length=255)
    zoho_payment_id: Optional[str] = Field(None, description="Zoho payment ID", max_length=255)

    # Platform configuration
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). Used for Zoho configuration selection")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v) -> Optional[str]:
        if v is not None:
            allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due']
            if v.lower() not in allowed_statuses:
                raise ValueError(f'Status must be one of: {allowed_statuses}')
            return v.lower()
        return v

    @field_validator('subscription_status')
    @classmethod
    def validate_subscription_status(cls, v) -> Optional[str]:
        if v is not None:
            allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due', 'pending']
            if v.lower() not in allowed_statuses:
                raise ValueError(f'Subscription status must be one of: {allowed_statuses}')
            return v.lower()
        return v

    @field_validator('currency_code')
    @classmethod
    def validate_currency_code(cls, v) -> Optional[str]:
        if v is not None:
            if v.upper() not in ['USD', 'EUR', 'GBP', 'INR', 'CAD', 'AUD']:
                raise ValueError('Currency code must be a valid 3-letter code')
            return v.upper()
        return v
