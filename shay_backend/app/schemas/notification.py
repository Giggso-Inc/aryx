"""
Notification schemas for request/response validation

This module defines Pydantic schemas for realtime notification preferences.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from uuid import UUID


class RealtimeNotificationResponse(BaseModel):
    """Schema for realtime notification settings response"""
    id: Optional[str] = Field(None, description="Notification preference ID")
    user_id: str = Field(..., description="User ID")
    workspace_id: Optional[str] = Field(None, description="Workspace ID")
    channel_id: Optional[str] = Field(None, description="Channel ID")
    is_notifications_enabled: bool = Field(..., description="Master switch for all notifications")
    apps_enabled: Optional[List[str]] = Field(default=[], description="List of enabled app IDs")
    is_post_enabled: bool = Field(..., description="Post notifications enabled")
    is_mention_enabled: bool = Field(..., description="Mention notifications enabled")
    is_task_enabled: bool = Field(..., description="Task notifications enabled")
    is_approval_enabled: bool = Field(..., description="Approval notifications enabled")
    is_new_email_enabled: bool = Field(..., description="New email notifications enabled")
    is_email_reply_enabled: bool = Field(..., description="Email reply notifications enabled")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


class RealtimeNotificationSaveRequest(BaseModel):
    """Schema for saving notification settings"""
    workspace_id: str = Field(..., description="Workspace ID")
    channel_id: str = Field(..., description="Channel ID")
    is_notifications_enabled: bool = Field(..., description="Master switch for all notifications")
    apps_enabled: Optional[List[str]] = Field(default=[], description="List of enabled app IDs")
    is_post_enabled: bool = Field(..., description="Post notifications enabled")
    is_mention_enabled: bool = Field(..., description="Mention notifications enabled")
    is_task_enabled: bool = Field(..., description="Task notifications enabled")
    is_approval_enabled: bool = Field(..., description="Approval notifications enabled")
    is_new_email_enabled: bool = Field(..., description="New email notifications enabled")
    is_email_reply_enabled: bool = Field(..., description="Email reply notifications enabled")


class RealtimeNotificationUpdateRequest(BaseModel):
    """Schema for updating notification settings"""
    id: str = Field(..., description="Notification preference ID (primary key)")
    workspace_id: str = Field(..., description="Workspace ID")
    channel_id: str = Field(..., description="Channel ID")
    is_notifications_enabled: bool = Field(..., description="Master switch for all notifications")
    apps_enabled: Optional[List[str]] = Field(default=[], description="List of enabled app IDs")
    is_post_enabled: bool = Field(..., description="Post notifications enabled")
    is_mention_enabled: bool = Field(..., description="Mention notifications enabled")
    is_task_enabled: bool = Field(..., description="Task notifications enabled")
    is_approval_enabled: bool = Field(..., description="Approval notifications enabled")
    is_new_email_enabled: bool = Field(..., description="New email notifications enabled")
    is_email_reply_enabled: bool = Field(..., description="Email reply notifications enabled")


class EmailNotifySettingsResponse(BaseModel):
    """Schema for email notification settings response"""
    id: Optional[str] = Field(None, description="Email notification settings ID")
    resource_id: Optional[str] = Field(None, description="User ID (resource identifier)")
    routine: Optional[int] = Field(None, description="Notification frequency in minutes (15, 30, 45, 60, 240, 480, 720, 1440)")
    is_notification_enabled: int = Field(0, description="Master switch for all notifications (0 = disabled, 1 = enabled)")
    post_enabled: int = Field(0, description="Post notifications enabled (0 = disabled, 1 = enabled)")
    app_enabled: int = Field(0, description="App notifications enabled (0 = disabled, 1 = enabled)")
    blocker_enabled: int = Field(0, description="Blocker notifications enabled (0 = disabled, 1 = enabled)")
    approval_pending_enabled: int = Field(0, description="Approval pending notifications enabled (0 = disabled, 1 = enabled)")
    meeting_enabled: int = Field(0, description="Meeting notifications enabled (0 = disabled, 1 = enabled)")
    task_enabled: int = Field(0, description="Task notifications enabled (0 = disabled, 1 = enabled)")
    mention_enabled: int = Field(0, description="Mention notifications enabled (0 = disabled, 1 = enabled)")
    reply_enabled: int = Field(0, description="Reply notifications enabled (0 = disabled, 1 = enabled)")
    chat_enabled: int = Field(0, description="Chat notifications enabled (0 = disabled, 1 = enabled)")
    friend_enabled: int = Field(0, description="Friend notifications enabled (0 = disabled, 1 = enabled)")
    created_by: Optional[str] = Field(None, description="User ID who created the record")
    updated_by: Optional[str] = Field(None, description="User ID who updated the record")
    created_time: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_time: Optional[datetime] = Field(None, description="Last update timestamp")
    last_email_notify_time: Optional[datetime] = Field(None, description="Last email notification timestamp")

    class Config:
        from_attributes = True


class EmailNotifySettingsSaveRequest(BaseModel):
    """Schema for saving email notification settings"""
    resource_id: str = Field(..., description="User ID (resource identifier)")
    routine: Optional[int] = Field(None, description="Notification frequency in minutes (15, 30, 45, 60, 240, 480, 720, 1440)")
    is_notification_enabled: int = Field(0, description="Master switch for all notifications (0 = disabled, 1 = enabled)")
    post_enabled: int = Field(0, description="Post notifications enabled (0 = disabled, 1 = enabled)")
    app_enabled: int = Field(0, description="App notifications enabled (0 = disabled, 1 = enabled)")
    blocker_enabled: int = Field(0, description="Blocker notifications enabled (0 = disabled, 1 = enabled)")
    approval_pending_enabled: int = Field(0, description="Approval pending notifications enabled (0 = disabled, 1 = enabled)")
    meeting_enabled: int = Field(0, description="Meeting notifications enabled (0 = disabled, 1 = enabled)")
    task_enabled: int = Field(0, description="Task notifications enabled (0 = disabled, 1 = enabled)")
    mention_enabled: int = Field(0, description="Mention notifications enabled (0 = disabled, 1 = enabled)")
    reply_enabled: int = Field(0, description="Reply notifications enabled (0 = disabled, 1 = enabled)")
    chat_enabled: int = Field(0, description="Chat notifications enabled (0 = disabled, 1 = enabled)")
    friend_enabled: int = Field(0, description="Friend notifications enabled (0 = disabled, 1 = enabled)")


class EmailNotifySettingsUpdateRequest(BaseModel):
    """Schema for updating email notification settings"""
    id: str = Field(..., description="Email notification settings ID (primary key)")
    resource_id: str = Field(..., description="User ID (resource identifier)")
    routine: Optional[int] = Field(None, description="Notification frequency in minutes (15, 30, 45, 60, 240, 480, 720, 1440)")
    is_notification_enabled: int = Field(0, description="Master switch for all notifications (0 = disabled, 1 = enabled)")
    post_enabled: int = Field(0, description="Post notifications enabled (0 = disabled, 1 = enabled)")
    app_enabled: int = Field(0, description="App notifications enabled (0 = disabled, 1 = enabled)")
    blocker_enabled: int = Field(0, description="Blocker notifications enabled (0 = disabled, 1 = enabled)")
    approval_pending_enabled: int = Field(0, description="Approval pending notifications enabled (0 = disabled, 1 = enabled)")
    meeting_enabled: int = Field(0, description="Meeting notifications enabled (0 = disabled, 1 = enabled)")
    task_enabled: int = Field(0, description="Task notifications enabled (0 = disabled, 1 = enabled)")
    mention_enabled: int = Field(0, description="Mention notifications enabled (0 = disabled, 1 = enabled)")
    reply_enabled: int = Field(0, description="Reply notifications enabled (0 = disabled, 1 = enabled)")
    chat_enabled: int = Field(0, description="Chat notifications enabled (0 = disabled, 1 = enabled)")
    friend_enabled: int = Field(0, description="Friend notifications enabled (0 = disabled, 1 = enabled)")