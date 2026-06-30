"""
Invitation model for user invitations
"""

from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID

from app.core.database import Base


class Invitation(Base):
    """Invitation model for user invitations"""
    
    __tablename__ = "gg_invitations"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Invitation details
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False, default="user")
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    invited_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_invitation_hash', 'id'),
        Index('idx_invitation_email', 'email'),
        Index('idx_invitation_company', 'company_id'),
        Index('idx_invitation_status', 'status'),
    )
    
    def __repr__(self):
        return f"<Invitation(id={self.id}, email={self.email}, company_id={self.company_id})>"
    
    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid"""
        return self.status == "pending" and datetime.utcnow() < self.expires_at
    
    def mark_as_used(self):
        """Mark invitation as used"""
        self.status = "used"
        self.updated_at = datetime.utcnow()
    
    def mark_as_expired(self):
        """Mark invitation as expired"""
        self.status = "expired"
        self.updated_at = datetime.utcnow() 