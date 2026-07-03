"""
Pydantic schemas for subscription plan operations
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, validator
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class SubscriptionPlanBase(BaseModel):
    """Base schema for subscription plan operations."""
    name: str = Field(..., description="Plan name", min_length=1, max_length=255)
    plan_code: str = Field(..., description="Unique plan code", min_length=1, max_length=50)
    description: Optional[str] = Field(None, description="Plan description")
    monthly_price: Decimal = Field(..., description="Monthly price", ge=0)
    plan_cycles: int = Field(..., description="Number of plan cycles", ge=1)
    
    # Billing configuration
    interval: int = Field(..., description="Billing interval", ge=1)
    interval_unit: str = Field(..., description="Billing interval unit (month, year, etc.)", max_length=20)
    interval_count: int = Field(..., description="Number of intervals", ge=1)
    
    # Features and metadata
    features: Optional[Any] = Field(None, description="Plan features (dictionary or list)")
    sort_order: int = Field(0, description="Sort order for display")
    is_active: bool = Field(True, description="Whether the plan is active")

    @validator('features')
    def validate_features(cls, v):
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
    def validate_interval_unit(cls, v):
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
    def validate_features(cls, v):
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
    def validate_interval_unit(cls, v):
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


class SubscriptionPlanResponse(SubscriptionPlanBase):
    """Schema for subscription plan responses."""
    id: UUID
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    @validator('plan_cycles', pre=True)
    def ensure_positive_plan_cycles(cls, value):
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


class SubscriptionPlanNodeResponse(BaseModel):
    """Subscription plan response schema matching Node.js API format"""
    name: str
    planCode: str
    description: Optional[str] = None
    monthlyPrice: str
    planCycles: int
    features: Optional[list] = None
    isActive: bool
    sortOrder: int
    createdAt: str
    updatedAt: str
    zohoPlanId: Optional[str] = None
    zohoProductId: Optional[str] = None
    intervalCount: int
    deletedAt: Optional[str] = None
    zohoPlanCode: Optional[str] = None
    zohoProductCode: Optional[str] = None
    zohoBillingCycle: Optional[str] = None
    updatedBy: Optional[str] = None
    intervalUnit: str
    interval: int
    id: str
    createdBy: Optional[str] = None
    subscriberCount: str
    createdByEmail: str
    createdByRole: str
    createdById: str
    zohoSubscriptionId: Optional[str] = None
    subscriptionStatus: Optional[str] = None
    endDate: Optional[str] = None
    cancelAtPeriodEnd: Optional[bool] = None
    zohoCustomerId: Optional[str] = None
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
