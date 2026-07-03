"""
Company model for multi-tenant support
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.db_types import UUID, JSONB


class Company(Base):
    """Company model for multi-tenant support"""
    
    __tablename__ = "gg_company"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Company information
    name = Column(String(255), nullable=False, index=True)
    domain = Column(String(255), unique=True, nullable=True, index=True)
    description = Column(Text, nullable=True)
    website_url = Column(String(500), nullable=True)  # Added from DDL
    
    # Company settings
    is_active = Column(Boolean, default=True, nullable=False)
    settings = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # Subscription and limits
    subscription_plan = Column(String(50), default="free", nullable=False)
    max_users = Column(String(10), default="10", nullable=False)
    max_workspaces = Column(String(10), default="5", nullable=False)
    max_storage_gb = Column(String(10), default="1", nullable=False)
    
    # AI integration settings
    ai_enabled = Column(Boolean, default=True, nullable=False)
    ai_provider = Column(String(50), default="openai", nullable=False)
    ai_webhook_url = Column(String(500), nullable=True)
    
    # User tracking
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    users = relationship("User", back_populates="company")
    subscriptions = relationship("Subscription", back_populates="company")
    
    # Dialect-agnostic indexes (hash applied only on PostgreSQL via create_postgresql_optimizations)
    __table_args__ = (
        Index('idx_company_name_hash', 'name'),
        Index('idx_company_domain_hash', 'domain'),
    )
    
    def __repr__(self):
        return f"<Company(id={self.id}, name={self.name}, domain={self.domain})>"
    
    @property
    def is_premium(self) -> bool:
        """Check if company has premium subscription"""
        return self.subscription_plan in ["premium", "enterprise"]
    
    @property
    def is_enterprise(self) -> bool:
        """Check if company has enterprise subscription"""
        return self.subscription_plan == "enterprise"
    
    def get_max_users(self) -> int:
        """Get maximum number of users"""
        return int(self.max_users)
    
    def get_max_workspaces(self) -> int:
        """Get maximum number of workspaces"""
        return int(self.max_workspaces)
    
    def get_max_storage_gb(self) -> int:
        """Get maximum storage in GB"""
        return int(self.max_storage_gb) 