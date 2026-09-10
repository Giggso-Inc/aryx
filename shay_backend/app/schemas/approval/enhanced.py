"""
Enhanced approval schemas (history/detail/list-with-history).

Split out of the former app/schemas/approval.py to keep each file under
the Raven 150-line style limit.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ApprovalHistoryItem(BaseModel):
    """Schema for individual approval history items."""

    action: str = Field(..., description="Action taken (e.g., 'Approval Created', 'Status Changed', 'Reassigned')")
    details: str = Field(..., description="Detailed description of the action")
    timestamp: datetime = Field(..., description="When the action occurred")
    user: Dict[str, Any] = Field(..., description="User who performed the action")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata for the action")


class ApprovalDetails(BaseModel):
    """Schema for detailed approval information."""

    approval_name: str = Field(..., description="Title of the approval")
    status: str = Field(..., description="Current status of the approval")
    approver: Optional[Dict[str, Any]] = Field(None, description="Current approver user details")
    created_by: Optional[Dict[str, Any]] = Field(None, description="User who originally created the approval")
    requested_by: Optional[Dict[str, Any]] = Field(None, description="User who last requested approval to somebody")
    title: str = Field(..., description="Approval title")
    description: Optional[str] = Field(None, description="Approval description")
    approval_notes: Optional[str] = Field(None, description="Notes from approver")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection if applicable")
    comment: Optional[str] = Field(None, description="General comment")
    created_at: datetime = Field(..., description="When the approval was created")
    updated_at: datetime = Field(..., description="When the approval was last updated")
    approved_at: Optional[datetime] = Field(None, description="When the approval was approved")
    rejected_at: Optional[datetime] = Field(None, description="When the approval was rejected")
    approval_metadata: Optional[Dict[str, Any]] = Field(None, description="Approval metadata")


class EnhancedApprovalResponse(BaseModel):
    """Schema for enhanced approval response with history and context."""

    id: str = Field(..., description="Approval ID")
    approval_details: ApprovalDetails = Field(..., description="Detailed approval information")
    approval_history: List[ApprovalHistoryItem] = Field(..., description="History of approval actions")
    context: Dict[str, Any] = Field(..., description="Context information (workspace, channel, thread)")


class ApprovalCountResponse(BaseModel):
    """Schema for approval count response"""
    approval_count: int = Field(..., description="Total number of approvals for the user")

    class Config:
        from_attributes = True


class ApprovalListResponse(BaseModel):
    """Schema for approval list response with enhanced data."""

    approvals: List[EnhancedApprovalResponse] = Field(..., description="List of approvals with full details")
    total: int = Field(..., description="Total number of approvals")
    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Page size")
    has_more: bool = Field(..., description="Whether there are more pages")
