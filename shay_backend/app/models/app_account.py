"""
AppAccount model for mapping apps to channels
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.db_types import UUID, JSONB

from app.core.database import Base


class AppAccount(Base):
    """AppAccount model for mapping apps to channels with metadata"""
    
    __tablename__ = "gg_app_accounts"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Foreign keys
    app_id = Column(UUID(as_uuid=True), ForeignKey("gg_apps.id"), nullable=False, index=True)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id"), nullable=False, index=True)
    connected_by = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=False, index=True)
    
    # Connection metadata
    connection_name = Column(String(255), nullable=True)
    connection_status = Column(String(50), default="active", nullable=False)  # active, inactive, error
    connection_settings = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # Connection details
    api_key = Column(String(500), nullable=True)  # Encrypted API key
    webhook_url = Column(String(500), nullable=True)
    callback_url = Column(String(500), nullable=True)
    
    # Connection metadata
    last_sync_at = Column(DateTime, nullable=True)
    sync_status = Column(String(50), nullable=True)  # success, failed, pending
    error_message = Column(Text, nullable=True)
    
    # Connection settings
    is_active = Column(Boolean, default=True, nullable=False)
    auto_sync = Column(Boolean, default=False, nullable=False)
    sync_interval = Column(Integer, default=3600, nullable=False)  # seconds
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    app = relationship("App", backref="app_accounts")
    channel = relationship("Channel", backref="app_accounts")
    user = relationship("User", backref="app_accounts")
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_app_account_app_channel', 'app_id', 'channel_id'),
        Index('idx_app_account_status_time', 'connection_status', 'created_at'),
        Index('idx_app_account_sync_status', 'sync_status', 'last_sync_at'),
        Index('idx_app_account_active_sync', 'is_active', 'auto_sync'),
        Index('idx_app_account_connected_by', 'connected_by', 'created_at'),
    )
    
    def __repr__(self):
        return f"<AppAccount(id={self.id}, app_id={self.app_id}, channel_id={self.channel_id})>"
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": str(self.id),
            "app_id": str(self.app_id),
            "channel_id": str(self.channel_id),
            "connected_by": str(self.connected_by),
            "connection_name": self.connection_name,
            "connection_status": self.connection_status,
            "connection_settings": self.connection_settings,
            "webhook_url": self.webhook_url,
            "callback_url": self.callback_url,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "sync_status": self.sync_status,
            "error_message": self.error_message,
            "is_active": self.is_active,
            "auto_sync": self.auto_sync,
            "sync_interval": self.sync_interval,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        } 