"""
Task create/update request schemas.

File: app/schemas/task/create_update.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Split out of the former app/schemas/task.py (via requests.py) to keep each
file under the Raven 150-line style limit. Contains the TaskCreate and
TaskUpdate request schemas, including their due_date parsing validators.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID
import re

from .base import TaskBase


class TaskCreate(TaskBase):
    """Schema for creating a new task"""
    # Only message_id is required for context - other context fields are auto-filled
    message_id: Union[str, UUID] = Field(..., description="Message ID to associate task with")

    # Optional context fields (will be auto-filled from message if not provided)
    workspace_id: Optional[Union[str, UUID]] = Field(None, description="Workspace ID (auto-filled from message)")
    channel_id: Optional[Union[str, UUID]] = Field(None, description="Channel ID (auto-filled from message)")
    thread_id: Optional[Union[str, UUID]] = Field(None, description="Thread ID (auto-filled from message)")

    # Required assignment - user must be specified and must be a member of the channel
    assigned_to: Union[str, UUID] = Field(..., description="User ID assigned to the task (must be a member of the channel)")

    checklists: Optional[List[Dict[str, Any]]] = Field(None, description="Initial checklist items")
    # Each checklist item should have: {"text": "item text", "order_index": 0}

    # Optional message content and attachments for task context
    message_content: Optional[str] = Field(None, description="Message content to create with task (optional)")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with the message (optional)")


class TaskUpdate(BaseModel):
    """Schema for updating a task"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[Union[str, UUID]] = None
    status: Optional[str] = None
    source: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    task_metadata: Optional[Dict[str, Any]] = None

    # Optional message content and attachments for task update context
    message_content: Optional[str] = Field(None, description="Message content to create with task update (optional)")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with the message (optional)")

    # Note: workspace_id, channel_id, thread_id, and message_id cannot be updated
    # as they define the task's context and are immutable

    @validator('status')
    def validate_status(cls, v) -> str:
        """Validate task status values for updates"""
        if v is not None:
            valid_statuses = ['Open', 'In Progress', 'On Hold', 'Close']
            if v not in valid_statuses:
                raise ValueError(f'Status must be one of: {valid_statuses}')
        return v

    @validator('source')
    def validate_source(cls, v) -> Optional[str]:
        if v is not None:
            valid_sources = ['ai_generated', 'manual', 'system']
            if v not in valid_sources:
                raise ValueError(f'Source must be one of: {valid_sources}')
        return v

    @validator('priority')
    def validate_priority(cls, v) -> str:
        """Validate task priority values for updates"""
        if v is not None:
            valid_priorities = ['Low', 'Medium', 'High', 'Critical', 'Blocker']
            if v not in valid_priorities:
                raise ValueError(f'Priority must be one of: {valid_priorities}')
        return v

    @validator('due_date', pre=True)
    def parse_due_date(cls, v) -> Optional[datetime]:
        """Parse due_date from various formats including custom timezone format"""
        if v is None:
            return v

        if isinstance(v, datetime):
            # If it's already a datetime, convert to naive datetime for database compatibility
            return v.replace(tzinfo=None) if v.tzinfo else v

        if isinstance(v, str):
            # Handle custom format: "2025-09-02 10:15:00 +0530"
            if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+\d{4}', v):
                # Convert custom format to ISO format
                # "2025-09-02 10:15:00 +0530" -> "2025-09-02T10:15:00+05:30"
                date_part, time_part, tz_part = v.split(' ')
                iso_format = f"{date_part}T{time_part}{tz_part[:3]}:{tz_part[3:]}"
                dt = datetime.fromisoformat(iso_format)
                # Convert to naive datetime for database compatibility
                return dt.replace(tzinfo=None)

            # Handle other formats
            try:
                dt = datetime.fromisoformat(v)
                # Convert to naive datetime for database compatibility
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except ValueError:
                # Try parsing with other common formats
                try:
                    dt = datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
                    return dt
                except ValueError:
                    raise ValueError(f'Invalid datetime format: {v}')

        raise ValueError(f'Invalid due_date type: {type(v)}')
