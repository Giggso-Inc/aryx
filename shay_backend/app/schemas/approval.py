"""
Pydantic Schemas for Approval Requests and Responses

This module defines Pydantic models for validation and serialization of approval
data. These schemas ensure data integrity and provide clear API contracts for
the approval system.

Features:
- Input validation for approval creation and updates
- Response serialization with proper data types
- Field validation and constraints
- Optional field handling for flexible requests
- Auto-generation support for missing fields

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0
"""

# Type hints for optional fields and collections
from typing import Optional, List, Dict, Any
# Date and time handling for timestamps
from datetime import datetime
# Pydantic base classes and field validation
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


# Enhanced schemas for approval history tracking
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
