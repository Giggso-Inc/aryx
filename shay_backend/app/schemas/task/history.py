"""
Enhanced task history/detail schemas.

File: app/schemas/task/history.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Split out of the former app/schemas/task.py to keep each file under the
Raven 150-line style limit. Contains the enhanced task response with
history/timeline support used by the task list and detail endpoints.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from uuid import UUID


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
