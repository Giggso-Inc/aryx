"""
Channel model for user-created channels that reference workspaces (tags)
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Channel(Base):
    """Channel model for user-created channels that reference workspaces (tags)"""
    
    __tablename__ = "gg_channels"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Channel information
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Optional tags; null in DB when not provided or empty
    channel_tags = Column(JSONB, nullable=True)
    # Optional sub-tags; null in DB when not provided or empty
    channel_sub_tags = Column(JSONB, nullable=True)
    
    # Workspace association (tag/workspace)
    workspace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True, index=True)

    # Channel settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    channel_type = Column(Integer, default=1, nullable=False)
    channel_settings = Column(JSONB, nullable=True)  # Renamed from settings to avoid SQLAlchemy conflict
    
    # Channel metadata
    message_count = Column(Integer, default=0, nullable=False)
    last_message_at = Column(DateTime, nullable=True)
    
    # AI integration settings (inherited from workspace)
    ai_enabled = Column(Boolean, default=True, nullable=False)
    
    # User tracking
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    
    # Dialect-agnostic indexes
    __table_args__ = (
        Index('idx_channel_name_hash', 'name'),
        Index('idx_channel_workspace_time', 'workspace_id', 'created_at'),
        Index('idx_channel_active_public', 'is_active', 'is_public'),
        Index('idx_channel_archived', 'is_archived'),
        Index('idx_channel_last_message', 'last_message_at'),
        # Unique constraint to prevent same name in same workspace
        Index('idx_channel_name_workspace_unique', 'name', 'workspace_id', unique=True),
    )
    
    def __repr__(self):
        return f"<Channel(id={self.id}, name={self.name}, workspace_id={self.workspace_id})>"
    
    def is_accessible_by_user(self, user_company_id: str, user_role: str) -> bool:
        """Check if channel is accessible by user.
        company_id is not stored on gg_channels; access is enforced via gg_members membership.
        """
        return True
    
    def get_title_or_default(self) -> str:
        """Get channel title or default title"""
        return self.name or f"Channel {str(self.id)[:8]}" 
