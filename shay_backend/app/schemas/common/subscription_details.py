"""
Subscription validation / company subscription details schemas.

Split out of the former app/schemas/common.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SubscriptionValidationRequest(BaseModel):
    """Request schema for subscription validation. channelId is optional: omit it when only checking if the company can create a channel (user_id is enough); send it when checking message (and attachment) limits in an existing channel."""
    channelId: Optional[str] = Field(None, description="Optional. Omit when checking canCreateChannel only. Send a valid channel UUID when checking canCreateMessage (and canCreateAttachment).")


class CompanySubscriptionDetailsRequest(BaseModel):
    """Request schema for fetching company subscription details"""
    companyId: str = Field(..., description="Company ID")


class CompanyInvoiceDetailsResponse(BaseModel):
    """Response schema for company invoice details only (simple API)"""
    invoiceDetails: Optional[list] = None
    totalCost: Optional[str] = None


class CompanySubscriptionDetailsResponse(BaseModel):
    """Response schema for company subscription details"""
    currentPlan: Optional[str] = None
    currentPlanCode: Optional[str] = None
    planPeriod: Optional[str] = None
    subscriptionId: Optional[str] = None
    customerId: Optional[str] = None
    userInfo: Optional[dict] = None
    currentCost: Optional[str] = None
    nextInvoiceDate: Optional[str] = None
    companyGroupCount: Optional[int] = None
    sharedInboxCount: Optional[int] = None
    companyChannelCount: Optional[int] = None
    aiResponseCount: Optional[int] = None
    storageCount: Optional[int] = None
    invoiceDetails: Optional[list] = None
    totalCost: Optional[str] = None
    status: Optional[str] = None
    currentPlanStatus: Optional[str] = None
    addonDetails: Optional[dict] = None
    metadata: Optional[dict] = None
    expiresAt: Optional[str] = None
    usageStatistics: Optional[dict] = None
