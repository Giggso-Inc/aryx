"""
Pydantic schemas for subscription operations
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class SubscriptionBase(BaseModel):
    """Base schema for subscription operations."""
    company_id: UUID = Field(..., description="Company ID")
    plan_id: UUID = Field(..., description="Subscription plan ID")
    
    # Subscription details
    status: str = Field(..., description="Subscription status", max_length=50)
    subscription_status: str = Field(..., description="Detailed subscription status", max_length=50)
    
    # Billing information
    amount: Decimal = Field(..., description="Subscription amount", ge=0)
    currency_code: str = Field(..., description="Currency code", max_length=3)
    billing_cycle: str = Field(..., description="Billing cycle", max_length=50)
    auto_collect: bool = Field(True, description="Auto-collect payments")
    
    # Billing periods
    current_period_start: datetime = Field(..., description="Current period start date")
    current_period_end: datetime = Field(..., description="Current period end date")
    next_billing_date: Optional[datetime] = Field(None, description="Next billing date")
    
    # Trial information
    zoho_trial_end: Optional[datetime] = Field(None, description="Trial end date")
    zoho_cancel_at_period_end: bool = Field(False, description="Cancel at period end")
    
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
    def validate_status(cls, v):
        allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due']
        if v.lower() not in allowed_statuses:
            raise ValueError(f'Status must be one of: {allowed_statuses}')
        return v.lower()

    @field_validator('subscription_status')
    @classmethod
    def validate_subscription_status(cls, v):
        allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due', 'pending']
        if v.lower() not in allowed_statuses:
            raise ValueError(f'Subscription status must be one of: {allowed_statuses}')
        return v.lower()

    @field_validator('currency_code')
    @classmethod
    def validate_currency_code(cls, v):
        if v.upper() not in ['USD', 'EUR', 'GBP', 'INR', 'CAD', 'AUD']:
            raise ValueError('Currency code must be a valid 3-letter code')
        return v.upper()


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
    def validate_status(cls, v):
        if v is not None:
            allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due']
            if v.lower() not in allowed_statuses:
                raise ValueError(f'Status must be one of: {allowed_statuses}')
            return v.lower()
        return v

    @field_validator('subscription_status')
    @classmethod
    def validate_subscription_status(cls, v):
        if v is not None:
            allowed_statuses = ['active', 'inactive', 'cancelled', 'suspended', 'trial', 'past_due', 'pending']
            if v.lower() not in allowed_statuses:
                raise ValueError(f'Subscription status must be one of: {allowed_statuses}')
            return v.lower()
        return v

    @field_validator('currency_code')
    @classmethod
    def validate_currency_code(cls, v):
        if v is not None:
            if v.upper() not in ['USD', 'EUR', 'GBP', 'INR', 'CAD', 'AUD']:
                raise ValueError('Currency code must be a valid 3-letter code')
            return v.upper()
        return v


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
    def validate_features(cls, v):
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
