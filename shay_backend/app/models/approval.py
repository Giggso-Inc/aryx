"""
Approval Model for Thread-Level Message Approvals

This module defines the Approval SQLAlchemy ORM model for managing thread-level
message approval workflows. The approval system allows users to request approval
for messages in threads, assign approvers, and track approval statuses.

Features:
- Thread-level approvals (one active approval per thread)
- Message-specific approval requests
- User assignment and reassignment capabilities
- Status tracking (pending, approved, rejected)
- Audit trail with timestamps
- Soft delete functionality

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

Database Table: gg_approvals
"""

from sqlalchemy import Column, String, DateTime, Text, Index, ForeignKey
from app.core.db_types import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Approval(Base):
    """Approval requests for thread messages."""
    
    __tablename__ = "gg_approvals"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Foreign keys — linked only via message_id
    message_id = Column(UUID(as_uuid=True), ForeignKey("gg_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id", ondelete="CASCADE"), nullable=True, index=True)
    approver_user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Approval details
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending, approved, rejected
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    approval_notes = Column(Text, nullable=True)  # Notes from approver
    rejection_reason = Column(Text, nullable=True)  # Reason if rejected
    comment = Column(Text, nullable=True)  # General comment field for approve/reject actions
    
    # Metadata
    is_active = Column(String(1), nullable=False, default="Y")  # Y/N for soft delete
    approval_metadata = Column(JSONB, nullable=True, default={})  # For tracking approval history
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    
    # Relationships
    message = relationship("Message", back_populates="approvals")
    requested_by_user = relationship("User", foreign_keys=[requested_by_user_id], back_populates="requested_approvals")
    approver_user = relationship("User", foreign_keys=[approver_user_id], back_populates="assigned_approvals")

    # Dialect-agnostic indexes
    __table_args__ = (
        Index("idx_approver_status", "approver_user_id", "status"),
        Index("idx_requested_by_status", "requested_by_user_id", "status"),
        Index("idx_approval_id_hash", "id"),
    )

    def __repr__(self) -> str:
        return f"<Approval(id={self.id}, message_id={self.message_id}, status={self.status}, approver={self.approver_user_id})>"
    
    @property
    def is_pending(self) -> bool:
        """
        Check if approval is in pending status.
        
        Returns:
            bool: True if status is 'pending', False otherwise
        """
        return self.status == "pending"
    
    @property
    def is_approved(self) -> bool:
        """
        Check if approval has been approved.
        
        Returns:
            bool: True if status is 'approved', False otherwise
        """
        return self.status == "approved"
    
    @property
    def is_rejected(self) -> bool:
        """
        Check if approval has been rejected.
        
        Returns:
            bool: True if status is 'rejected', False otherwise
        """
        return self.status == "rejected"
    
    def can_be_approved_by(self, user_id: str) -> bool:
        """
        Check if a specific user can approve this request.
        
        Args:
            user_id (str): The user ID to check approval permissions for
            
        Returns:
            bool: True if user can approve, False otherwise
        """
        return str(self.approver_user_id) == str(user_id) and self.is_pending
    
    def can_be_reassigned_by(self, user_id: str) -> bool:
        """
        Check if a specific user can reassign this approval.
        
        Args:
            user_id (str): The user ID to check reassignment permissions for
            
        Returns:
            bool: True if user can reassign, False otherwise
        """
        return str(self.approver_user_id) == str(user_id) and self.is_pending 