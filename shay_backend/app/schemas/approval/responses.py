"""
Approval response/list/stats schemas.

Split out of the former app/schemas/approval.py to keep each file under
the Raven 150-line style limit.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class ApprovalResponse(BaseModel):
    """Schema for approval response."""

    id: str
    # thread_id and channel_id removed from model; kept optional for backwards compat
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    channel_id: Optional[str] = None
    requested_by_user_id: Optional[str] = None
    approver_user_id: Optional[str] = None
    status: str
    title: str
    description: Optional[str]
    approval_notes: Optional[str]
    rejection_reason: Optional[str]
    comment: Optional[str]
    is_active: str
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime]
    rejected_at: Optional[datetime]

    class Config:
        from_attributes = True


class ApprovalWithDetailsResponse(BaseModel):
    """Schema for approval response with user and channel details."""

    id: str
    # thread_id and channel_id removed from model; kept optional for backwards compat
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    requested_by_user_id: Optional[str] = None
    requested_by_user_name: Optional[str] = None
    requested_by_user_email: Optional[str] = None
    approver_user_id: Optional[str] = None
    approver_user_name: Optional[str] = None
    approver_user_email: Optional[str] = None
    status: str
    title: str
    description: Optional[str]
    approval_notes: Optional[str]
    rejection_reason: Optional[str]
    comment: Optional[str]
    is_active: str
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime]
    rejected_at: Optional[datetime]

    class Config:
        from_attributes = True


class ApprovalList(BaseModel):
    """Schema for list of approvals."""

    approvals: List[ApprovalWithDetailsResponse]
    total: int
    page: int
    size: int


class ApprovalStats(BaseModel):
    """Schema for approval statistics."""

    total_pending: int
    total_approved: int
    total_rejected: int
    total_approvals: int
