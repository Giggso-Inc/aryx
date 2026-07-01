"""
Invitation model for user invitations
"""

from datetime import datetime, timedelta, timezone
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

    @classmethod
    def create_invitation(
        cls,
        *,
        email: str,
        role: str,
        company_id,
        invited_by,
        message: str | None = None,
        expires_at: datetime | None = None,
    ) -> "Invitation":
        """Create a pending invitation with a default 7-day expiry."""
        return cls(
            email=email,
            role=role,
            company_id=company_id,
            invited_by=invited_by,
            status="pending",
            message=message,
            expires_at=expires_at or (datetime.utcnow() + timedelta(days=7)),
        )
    
    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid"""
        return self.status == "pending" and self._utc_now_for(self.expires_at) < self.expires_at
    
    def mark_as_used(self):
        """Mark invitation as used"""
        self.status = "used"
        self.updated_at = datetime.utcnow()

    def accept(self):
        """Backward-compatible alias for marking the invitation as used."""
        self.mark_as_used()

    def mark_as_expired(self):
        """Mark invitation as expired"""
        self.status = "expired"
        self.updated_at = datetime.utcnow()

    @property
    def email_id(self) -> str:
        """Backward-compatible alias used by older routes."""
        return self.email
    @staticmethod
    def _utc_now_for(value: datetime | None) -> datetime:
        """Return a UTC timestamp that matches the target datetime awareness."""
        if value and value.tzinfo is not None and value.utcoffset() is not None:
            return datetime.now(timezone.utc)
        return datetime.utcnow()
