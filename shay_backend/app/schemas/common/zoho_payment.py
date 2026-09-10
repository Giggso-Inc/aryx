"""
Zoho hosted-page / subscription payment request+response schemas.

Split out of the former app/schemas/common.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ZohoHostedPageRequest(BaseModel):
    """Zoho hosted page creation request schema"""
    plan: dict = Field(..., description="Plan information")
    redirectUrl: str = Field(..., description="Redirect URL after payment")
    customer: dict = Field(..., description="Customer information")
    autoCollect: bool = Field(True, description="Auto collect payment")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class ZohoHostedPageResponse(BaseModel):
    """Zoho hosted page creation response schema"""
    hostedPageId: str = Field(..., description="Hosted page ID")
    url: str = Field(..., description="Hosted page URL")
    planId: str = Field(..., description="Plan ID")
    planName: str = Field(..., description="Plan name")
    amount: float = Field(..., description="Amount")
    companyId: str = Field(..., description="Company ID")
    companyName: str = Field(..., description="Company name")
    expiresAt: str = Field(..., description="Expiration time")


class UpdateCompanyPlanRequest(BaseModel):
    """Request schema for updating company plan"""
    companyId: str = Field(..., description="Company ID")
    newPlanId: str = Field(..., description="New subscription plan ID")
    subscriptionId: Optional[str] = Field(None, description="Zoho subscription ID (optional)")
    hostedPageId: Optional[str] = Field(None, description="Zoho hosted page ID (optional)")
    zohoCustomerId: Optional[str] = Field(None, description="Zoho customer ID (optional)")


class SubscriptionUpdateRequest(BaseModel):
    """Request schema for updating subscription via hosted page"""
    subscriptionId: str = Field(..., description="Zoho subscription ID")
    plan: Optional[dict] = Field(None, description="Plan information for update")
    addons: Optional[list] = Field(None, description="List of addons")
    referenceId: Optional[str] = Field(None, description="Reference ID")
    startsAt: Optional[str] = Field(None, description="Start date for subscription")
    customFields: Optional[list] = Field(None, description="Custom fields")
    couponCode: Optional[str] = Field(None, description="Coupon code")
    redirectUrl: Optional[str] = Field(None, description="Redirect URL after payment")
    salespersonName: Optional[str] = Field(None, description="Sales person name")
    canChargeSetupFeeImmediately: Optional[bool] = Field(None, description="Charge setup fee immediately")
    exchangeRate: Optional[float] = Field(None, description="Exchange rate")
    placeOfSupply: Optional[str] = Field(None, description="Place of supply")
    gstTreatment: Optional[str] = Field(None, description="GST treatment")
    gstNo: Optional[str] = Field(None, description="GST number")
    cfdiUsage: Optional[str] = Field(None, description="CFDI usage")
    paymentGateways: Optional[list] = Field(None, description="Payment gateways")
    billingAddressId: Optional[str] = Field(None, description="Billing address ID")
    shippingAddressId: Optional[str] = Field(None, description="Shipping address ID")
    branchId: Optional[str] = Field(None, description="Branch ID")
    templateId: Optional[int] = Field(None, description="Template ID")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionCancelRequest(BaseModel):
    """Request schema for canceling a subscription"""
    subscriptionId: str = Field(..., description="Zoho subscription ID")
    cancelAtEnd: bool = Field(False, description="If true, cancel at end of term (non_renewing), if false, cancel immediately (cancelled)")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionReactivateRequest(BaseModel):
    """Request schema for reactivating a cancelled subscription"""
    subscriptionId: str = Field(..., min_length=1, description="Zoho subscription ID to reactivate")
    # Zoho requires billing_cycles (number of cycles after which subscription expires); use -1 for never expire, or e.g. 12 for 12 cycles
    billingCycles: Optional[int] = Field(12, description="Number of billing cycles for reactivated subscription; default 12. Use -1 for never expire.")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class ValidatePaymentRequest(BaseModel):
    """Request schema for validating payment"""
    hostedPageId: Optional[str] = Field(None, description="Zoho hosted page ID")
    subscriptionId: Optional[str] = Field(None, description="Zoho subscription ID (used if hostedPageId is not provided)")
    companyId: str = Field(..., description="Company ID")
    userId: Optional[str] = Field(None, description="User ID (optional)")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionCreateRequest(BaseModel):
    """Request schema for creating a subscription in Zoho"""
    customer: Optional[dict] = Field(None, description="Customer object (required for new customer)")
    customerId: Optional[str] = Field(None, description="Customer ID (required for existing customer)")
    plan: dict = Field(..., description="Plan information with plan_code, quantity, price, etc.")
    autoCollect: Optional[bool] = Field(True, description="Auto collect payment")
    referenceId: Optional[str] = Field(None, description="Reference ID")
    startsAt: Optional[str] = Field(None, description="Start date for subscription")
    addons: Optional[list] = Field(None, description="List of addons")
    couponCode: Optional[str] = Field(None, description="Coupon code")
    metadata: Optional[dict] = Field(None, description="Metadata for subscription")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")
