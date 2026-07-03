"""
Email notification settings model for daily summary notifications

This module defines the SQLAlchemy ORM model for email notification settings,
allowing users to configure which types of notifications they want to receive
in their daily summary emails.

Author: Generated based on Java model structure
Date: 2025-01-XX
Version: 1.0.0
"""

# SQLAlchemy core components for table definition and column types
from sqlalchemy import Column, DateTime, Integer, BigInteger, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID
import uuid as uuid_module

# Base class for SQLAlchemy declarative models
from app.core.database import Base


class EmailNotifySettings(Base):
    """Email notification settings model for daily summary notifications"""
    
    __tablename__ = "gg_email_notify_settings"
    
    # Primary key - Using native UUID for PostgreSQL with default generator
    # Note: We set id explicitly in routes, but keep default as fallback
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4, index=True)
    
    # Routine setting (frequency or type of notification routine)
    routine = Column(BigInteger, nullable=True)
    
    # Resource ID (user identifier) - UUID reference to gg_users table (no FK constraint)
    resource_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    # Master switch for all notifications (0 = disabled, 1 = enabled)
    is_notification_enabled = Column(Integer, nullable=False, default=0)
    
    # Notification type enable/disable flags (0 = disabled, 1 = enabled)
    post_enabled = Column(Integer, nullable=False, default=0)
    app_enabled = Column(Integer, nullable=False, default=0)
    blocker_enabled = Column(Integer, nullable=False, default=0)
    approval_pending_enabled = Column(Integer, nullable=False, default=0)
    meeting_enabled = Column(Integer, nullable=False, default=0)
    task_enabled = Column(Integer, nullable=False, default=0)
    mention_enabled = Column(Integer, nullable=False, default=0)
    reply_enabled = Column(Integer, nullable=False, default=0)
    chat_enabled = Column(Integer, nullable=False, default=0)
    friend_enabled = Column(Integer, nullable=False, default=0)
    
    # Audit fields - User IDs who created and updated the record (UUID references, no FK constraints)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_time = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_time = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Last email notification timestamp
    last_email_notify_time = Column(DateTime, nullable=True)
    
    # PostgreSQL-specific indexes for performance
    __table_args__ = (
        Index('idx_email_notify_resource', 'resource_id'),
        Index('idx_email_notify_routine', 'routine'),
        Index('idx_email_notify_resource_routine', 'resource_id', 'routine'),
    )
    
    def __repr__(self):
        return f"<EmailNotifySettings(id={self.id}, resource_id={self.resource_id}, routine={self.routine})>"
    
    def is_notification_type_enabled(self, notification_type: str) -> bool:
        """
        Check if a specific notification type is enabled.
        
        Args:
            notification_type: Type of notification (post, app, blocker, etc.)
            
        Returns:
            bool: True if the notification type is enabled (value is 1), False otherwise
        """
        attr_name = f"{notification_type}_enabled"
        if hasattr(self, attr_name):
            return getattr(self, attr_name) == 1
        return False
    
    def enable_notification(self, notification_type: str) -> None:
        """
        Enable a specific notification type.
        
        Args:
            notification_type: Type of notification to enable
        """
        attr_name = f"{notification_type}_enabled"
        if hasattr(self, attr_name):
            setattr(self, attr_name, 1)
    
    def disable_notification(self, notification_type: str) -> None:
        """
        Disable a specific notification type.
        
        Args:
            notification_type: Type of notification to disable
        """
        attr_name = f"{notification_type}_enabled"
        if hasattr(self, attr_name):
            setattr(self, attr_name, 0)
