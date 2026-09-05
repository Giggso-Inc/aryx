"""
Approval create/update/action/reassign request schemas.

Split out of the former app/schemas/approval.py to keep each file under
the Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ApprovalCreate(BaseModel):
    """Schema for creating a new approval request."""

    thread_id: Optional[str] = Field(None, description="ID of the thread for approval (auto-detected from message if not provided)")
    message_id: str = Field(..., description="ID of the message being approved")
    approver_user_id: str = Field(..., description="ID of the user assigned to approve")
    title: Optional[str] = Field(None, description="Title of the approval request (auto-generated if not provided)", max_length=255)
    description: Optional[str] = Field(None, description="Description of what needs approval (auto-generated if not provided)")


class ApprovalUpdate(BaseModel):
    """Schema for updating an approval request."""

    title: Optional[str] = Field(None, description="Title of the approval request", max_length=255)
    description: Optional[str] = Field(None, description="Description of what needs approval")
    approver_user_id: Optional[str] = Field(None, description="ID of the new approver user")


class ApprovalAction(BaseModel):
    """Schema for approval actions (approve/reject)."""

    action: str = Field(..., description="Action to take: 'approve' or 'reject'")
    comment: Optional[str] = Field(None, description="Comment from the approver")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection if action is 'reject'")


class ApprovalReassign(BaseModel):
    """Schema for reassigning an approval to another user."""

    new_approver_user_id: str = Field(..., description="ID of the new approver user")
    notes: Optional[str] = Field(None, description="Notes about the reassignment")
