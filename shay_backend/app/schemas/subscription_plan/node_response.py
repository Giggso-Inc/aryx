"""
Node.js-API-compatible subscription-plan response schema.

Split out of the former app/schemas/subscription_plan.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel


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
