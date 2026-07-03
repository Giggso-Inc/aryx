"""Workspace model for channel-based workspace management."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
from app.core.database import Base


class Workspace(Base):
    """Workspace model for channel-based workspace management"""
    
    __tablename__ = "gg_workspace"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Workspace information
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Company association (multi-tenant)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # User association (from DDL schema)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Added from DDL
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)  # Added from DDL
    
    # Workspace settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    settings = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # AI integration settings
    ai_enabled = Column(Boolean, default=True, nullable=False)
    ai_provider = Column(String(50), default="openai", nullable=False)
    ai_model = Column(String(100), default="gpt-4", nullable=False)
    ai_webhook_url = Column(String(500), nullable=True)
    
    # Workspace type
    workspace_type = Column(String(50), nullable=True)

    # Workspace limits
    max_messages = Column(String(10), default="1000", nullable=False)
    max_attachments = Column(String(10), default="100", nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Dialect-agnostic indexes
    __table_args__ = (
        Index('idx_workspace_name_hash', 'name'),
        Index('idx_workspace_company_user', 'company_id', 'user_id'),
        Index('idx_workspace_active_company', 'is_active', 'company_id'),
    )
    
    def __repr__(self):
        return f"<Workspace(id={self.id}, name={self.name}, company_id={self.company_id})>"
    
    def get_max_messages(self) -> int:
        """Get maximum number of messages"""
        return int(self.max_messages)
    
    def get_max_attachments(self) -> int:
        """Get maximum number of attachments"""
        return int(self.max_attachments)
    
    def is_accessible_by_user(self, user_company_id: str, user_role: str) -> bool:
        """Check if workspace is accessible by user"""
        if user_role == "admin":
            return True
        return str(self.company_id) == user_company_id 
