"""Email Verification Token model for email verification system."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID
import secrets

from app.core.database import Base


class EmailVerificationToken(Base):
    """Email verification token model"""
    
    __tablename__ = "gg_email_verification_tokens"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Token details
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    token_type = Column(String(50), nullable=False, default="company_signup")
    
    # Foreign keys
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=True, index=True)
    
    # Token status
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False, nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_verification_token_hash', 'token'),
        Index('idx_verification_email_type_used', 'email', 'token_type', 'is_used'),
        Index('idx_verification_expires', 'expires_at'),
    )
    
    def __repr__(self):
        return f"<EmailVerificationToken(id={self.id}, email={self.email}, token_type={self.token_type})>"

    @staticmethod
    def _normalize_utc(dt: datetime) -> datetime:
        """Return a UTC datetime with consistent tz-awareness for comparisons."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    
    @property
    def is_valid(self) -> bool:
        """Check if token is still valid"""
        now = self._normalize_utc(datetime.now(timezone.utc))
        expires_at = self._normalize_utc(self.expires_at)
        return (
            not self.is_used and
            now < expires_at
        )
    
    @property
    def is_expired(self) -> bool:
        """Check if token is expired"""
        now = self._normalize_utc(datetime.now(timezone.utc))
        expires_at = self._normalize_utc(self.expires_at)
        return now >= expires_at
    
    def mark_as_used(self):
        """Mark token as used"""
        self.is_used = True
        self.used_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    @classmethod
    def generate_token(cls) -> str:
        """Generate cryptographically secure URL-safe token"""
        return secrets.token_urlsafe(32)  # 32 bytes = ~43 characters
    
    @classmethod
    def create_token(
        cls,
        email: str,
        company_id,
        user_id,
        token_type: str = "company_signup",
        expires_in_hours: int = 24
    ) -> 'EmailVerificationToken':
        """Create a new verification token"""
        from uuid import uuid4
        
        token = cls(
            id=uuid4(),
            email=email,
            token=cls.generate_token(),
            token_type=token_type,
            company_id=company_id,
            user_id=user_id,
            expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
            is_used=False
        )
        
        return token
