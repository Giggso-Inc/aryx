"""
Task assignment/status/filter request schemas.

File: app/schemas/task/filters.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Split out of the former app/schemas/task.py (via requests.py) to keep each
file under the Raven 150-line style limit. Contains the smaller task
request schemas: assignment, status update, and filtering.
"""

from datetime import datetime, date
from typing import Optional, List, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID


class TaskAssignmentRequest(BaseModel):
    """Schema for assigning a task to a user"""
    assigned_to: Union[str, UUID] = Field(..., description="User ID to assign the task to")


class TaskStatusUpdateRequest(BaseModel):
    """Schema for updating task status"""
    status: str = Field(..., description="New task status")
    comments: Optional[str] = Field(None, description="Optional comments for status change")
    message_content: Optional[str] = Field(None, description="Message content to create with status update (optional)")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with the message (optional)")

    @validator('status')
    def validate_status(cls, v) -> str:
        """Validate task status values for status updates"""
        valid_statuses = ['Open', 'In Progress', 'On Hold', 'Close']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {valid_statuses}')
        return v


class TaskFilterRequest(BaseModel):
    """Schema for filtering tasks"""
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[Union[str, UUID]] = None
    workspace_id: Optional[Union[str, UUID]] = None
    channel_id: Optional[Union[str, UUID]] = None
    thread_id: Optional[Union[str, UUID]] = None
    source: Optional[str] = None
    due_date_from: Optional[date] = None
    due_date_to: Optional[date] = None
    created_date_from: Optional[datetime] = None
    created_date_to: Optional[datetime] = None
    tags: Optional[List[str]] = None
