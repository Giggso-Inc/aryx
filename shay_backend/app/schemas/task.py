"""
Task schemas for request/response validation

This module defines Pydantic schemas for task management including creation,
updates, responses, and validation rules.

File: app/schemas/task.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Comprehensive task validation with new status and priority values
- Checklist integration support
- Flexible filtering and pagination
- Status change tracking and comments
- Metadata and tagging support
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID
import re


class TaskBase(BaseModel):
    """Base schema for Task"""
    title: str = Field(..., min_length=1, max_length=255, description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    status: str = Field("Open", description="Task status: Open, In Progress, On Hold, Close")
    source: Optional[str] = Field(None, description="Task source: ai_generated, manual, system")
    due_date: Optional[datetime] = Field(None, description="Task due date and time")
    priority: str = Field("Medium", description="Task priority: Low, Medium, High, Critical, Blocker")
    tags: Optional[List[str]] = Field(None, description="List of tags")
    task_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional task metadata")

    @validator('status')
    def validate_status(cls, v):
        """Validate task status values for base task"""
        valid_statuses = ['Open', 'In Progress', 'On Hold', 'Close']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {valid_statuses}')
        return v

    @validator('source')
    def validate_source(cls, v):
        if v is not None:
            valid_sources = ['ai_generated', 'manual', 'system']
            if v not in valid_sources:
                raise ValueError(f'Source must be one of: {valid_sources}')
        return v

    @validator('priority')
    def validate_priority(cls, v):
        """Validate task priority values"""
        valid_priorities = ['Low', 'Medium', 'High', 'Critical', 'Blocker']
        if v not in valid_priorities:
            raise ValueError(f'Priority must be one of: {valid_priorities}')
        return v

    @validator('due_date', pre=True)
    def parse_due_date(cls, v):
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
    def validate_status(cls, v):
        """Validate task status values for updates"""
        if v is not None:
            valid_statuses = ['Open', 'In Progress', 'On Hold', 'Close']
            if v not in valid_statuses:
                raise ValueError(f'Status must be one of: {valid_statuses}')
        return v

    @validator('source')
    def validate_source(cls, v):
        if v is not None:
            valid_sources = ['ai_generated', 'manual', 'system']
            if v not in valid_sources:
                raise ValueError(f'Source must be one of: {valid_sources}')
        return v

    @validator('priority')
    def validate_priority(cls, v):
        """Validate task priority values for updates"""
        if v is not None:
            valid_priorities = ['Low', 'Medium', 'High', 'Critical', 'Blocker']
            if v not in valid_priorities:
                raise ValueError(f'Priority must be one of: {valid_priorities}')
        return v

    @validator('due_date', pre=True)
    def parse_due_date(cls, v):
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


class TaskResponse(TaskBase):
    """Schema for task response"""
    id: Union[str, UUID]  # Accept both string and UUID types
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    checklists: Optional[List[Dict[str, Any]]] = None  # Will be populated with checklist data
    
    # Additional user and context information
    assigned_user: Optional[Dict[str, Any]] = None  # User assigned to the task
    created_by_user: Optional[Dict[str, Any]] = None  # User who created the task
    channel: Optional[Dict[str, Any]] = None  # Channel information
    workspace: Optional[Dict[str, Any]] = None  # Workspace information

    class Config:
        from_attributes = True


class TaskList(BaseModel):
    """Schema for task list response"""
    tasks: List[TaskResponse]
    total: int
    page: int
    size: int

    class Config:
        from_attributes = True


class TaskStats(BaseModel):
    """Schema for task statistics with new status values"""
    total_tasks: int
    open_tasks: int
    in_progress_tasks: int
    on_hold_tasks: int
    closed_tasks: int
    overdue_tasks: int
    urgent_tasks: int


class TaskAssignmentRequest(BaseModel):
    """Schema for assigning a task to a user"""
    assigned_to: Union[str, UUID] = Field(..., description="User ID to assign the task to")


class TaskHistoryItem(BaseModel):
    """Schema for individual task history item"""
    action: str = Field(..., description="Action performed (e.g., 'Assigned to', 'Status changed to', 'Reassigned to')")
    details: str = Field(..., description="Detailed description of the action")
    timestamp: datetime = Field(..., description="When the action occurred")
    user: Optional[Dict[str, Any]] = Field(None, description="User who performed the action")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata for the action")

    class Config:
        from_attributes = True


class TaskDetails(BaseModel):
    """Schema for detailed task information"""
    task_name: str = Field(..., description="Task title/name")
    status: str = Field(..., description="Current task status")
    assignee: Optional[Dict[str, Any]] = Field(None, description="Complete user object for assignee")
    created_by: Optional[Dict[str, Any]] = Field(None, description="Complete user object for task creator")
    priority: str = Field(..., description="Task priority")
    description: Optional[str] = Field(None, description="Task description")
    due_date: Optional[datetime] = Field(None, description="Task due date and time")
    created_at: datetime = Field(..., description="When task was created")
    updated_at: datetime = Field(..., description="When task was last updated")
    source: Optional[str] = Field(None, description="Task source")
    tags: Optional[List[str]] = Field(None, description="Task tags")
    task_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional task metadata")

    class Config:
        from_attributes = True


class EnhancedTaskResponse(BaseModel):
    """Enhanced task response with history and details"""
    id: Union[str, UUID]
    task_details: TaskDetails
    task_history: List[TaskHistoryItem] = Field(default_factory=list, description="Task history timeline")
    checklists: Optional[List[Dict[str, Any]]] = Field(None, description="Task checklist items")
    context: Optional[Dict[str, Any]] = Field(None, description="Workspace, channel, thread context")

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """Task list response with enhanced structure"""
    tasks: List[EnhancedTaskResponse] = Field(..., description="List of enhanced task responses")
    total: int = Field(..., description="Total number of tasks")
    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Page size")
    has_more: bool = Field(..., description="Whether there are more pages")

    class Config:
        from_attributes = True


class TaskStatusUpdateRequest(BaseModel):
    """Schema for updating task status"""
    status: str = Field(..., description="New task status")
    comments: Optional[str] = Field(None, description="Optional comments for status change")
    message_content: Optional[str] = Field(None, description="Message content to create with status update (optional)")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with the message (optional)")

    @validator('status')
    def validate_status(cls, v):
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


class TaskCountResponse(BaseModel):
    """Schema for task count response"""
    task_count: int = Field(..., description="Total number of tasks matching the filters")
    
    class Config:
        from_attributes = True