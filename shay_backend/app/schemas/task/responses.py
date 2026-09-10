"""
Task response schemas.

File: app/schemas/task/responses.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Split out of the former app/schemas/task.py to keep each file under the
Raven 150-line style limit. Contains the plain task response/list/stats
schemas.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from uuid import UUID

from .base import TaskBase


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


class TaskCountResponse(BaseModel):
    """Schema for task count response"""
    task_count: int = Field(..., description="Total number of tasks matching the filters")

    class Config:
        from_attributes = True
