"""
RealtimeNotification model for storing user notification preferences

This module defines the SQLAlchemy ORM model for realtime email notification preferences.
Users can enable/disable notifications for specific actions: Post, Mention, Task, 
Approval, New Email, and Email Reply. Notifications are channel-based, so each user
can have different preferences for each channel. Each user-channel combination has
one row with separate boolean flags for each notification type.

Author: Auto-generated
Date: 2025-01-27
Version: 1.0.0
"""

# Standard library imports for date/time operations
from datetime import datetime

# SQLAlchemy core components for table definition and column types
from sqlalchemy import Column, String, DateTime, Boolean, Index, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from app.core.db_types import UUID, JSONB

# Base class for SQLAlchemy declarative models
from app.core.database import Base


class RealtimeNotification(Base):
    """RealtimeNotification model for storing user notification preferences per channel"""
    
    __tablename__ = "gg_realtime_notification"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # User association - Foreign key to gg_users
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Workspace association - Foreign key to gg_workspace (channels belong to workspaces)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("gg_workspace.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Channel association - Foreign key to gg_channels (notifications are channel-based)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Master switch to enable/disable all notifications - If False, no notifications will be sent regardless of individual flags
    is_notifications_enabled = Column(Boolean, nullable=False, default=True)
    
    # List of apps enabled by the user for notifications - Stored as JSONB array of app IDs (UUIDs)
    apps_enabled = Column(JSONB, nullable=True)  # Array of app UUIDs that are enabled for notifications (default: empty array/null)
    
    # Notification flags for each action type - Users can enable/disable each type individually per channel
    is_post_enabled = Column(Boolean, nullable=False, default=False)  # Post notifications
    is_mention_enabled = Column(Boolean, nullable=False, default=True)  # Mention in Internal comment notifications (enabled by default)
    is_task_enabled = Column(Boolean, nullable=False, default=False)  # Task notifications
    is_approval_enabled = Column(Boolean, nullable=False, default=False)  # Approval notifications
    is_new_email_enabled = Column(Boolean, nullable=False, default=False)  # New Email notifications
    is_email_reply_enabled = Column(Boolean, nullable=False, default=False)  # Email Reply notifications
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Unique constraint to ensure one preference per user per channel
    # Indexes for performance
    __table_args__ = (
        UniqueConstraint('user_id', 'channel_id', name='uq_user_channel_notification'),
        Index('idx_realtime_notification_user_id', 'user_id'),
        Index('idx_realtime_notification_workspace_id', 'workspace_id'),
        Index('idx_realtime_notification_channel_id', 'channel_id'),
        Index('idx_realtime_notification_user_channel', 'user_id', 'channel_id'),
    )
    
    def __repr__(self):
        return f"<RealtimeNotification(id={self.id}, user_id={self.user_id}, workspace_id={self.workspace_id}, channel_id={self.channel_id}, notifications_enabled={self.is_notifications_enabled}, apps_enabled={self.apps_enabled}, post={self.is_post_enabled}, mention={self.is_mention_enabled}, task={self.is_task_enabled}, approval={self.is_approval_enabled}, new_email={self.is_new_email_enabled}, email_reply={self.is_email_reply_enabled})>"
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "workspace_id": str(self.workspace_id),
            "channel_id": str(self.channel_id),
            "is_notifications_enabled": self.is_notifications_enabled,
            "apps_enabled": self.apps_enabled if self.apps_enabled else [],
            "is_post_enabled": self.is_post_enabled,
            "is_mention_enabled": self.is_mention_enabled,
            "is_task_enabled": self.is_task_enabled,
            "is_approval_enabled": self.is_approval_enabled,
            "is_new_email_enabled": self.is_new_email_enabled,
            "is_email_reply_enabled": self.is_email_reply_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    def is_app_enabled(self, app_id: str) -> bool:
        """
        Check if a specific app is enabled for notifications.
        
        Args:
            app_id: UUID string of the app to check
            
        Returns:
            bool: True if the app is in the apps_enabled list, False otherwise
        """
        if not self.apps_enabled:
            return False
        # Convert app_id to string for comparison (in case it's UUID object)
        app_id_str = str(app_id)
        return app_id_str in [str(aid) for aid in self.apps_enabled]
    
    def is_notification_enabled(self, notification_type: str) -> bool:
        """
        Check if a specific notification type is enabled for this user.
        First checks the master switch (is_notifications_enabled), then checks the specific type.
        
        Args:
            notification_type: One of 'post', 'mention', 'task', 'approval', 'new_email', 'email_reply'
            
        Returns:
            bool: True if notifications are enabled AND the specific notification type is enabled, False otherwise
        """
        # If master switch is off, no notifications are sent
        if not self.is_notifications_enabled:
            return False
        
        # Check specific notification type
        notification_map = {
            'post': self.is_post_enabled,
            'mention': self.is_mention_enabled,
            'task': self.is_task_enabled,
            'approval': self.is_approval_enabled,
            'new_email': self.is_new_email_enabled,
            'email_reply': self.is_email_reply_enabled
        }
        return notification_map.get(notification_type.lower(), False)
