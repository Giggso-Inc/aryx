"""
Task schemas package (re-exports).

File: app/schemas/task/__init__.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

This package replaces the former single-file app/schemas/task.py, split
into base/requests/responses/history modules to keep each file under the
Raven 150-line style limit. All public names are re-exported here so
existing `from app.schemas.task import X` imports keep working unchanged.
"""

from .base import TaskBase
from .create_update import TaskCreate, TaskUpdate
from .filters import (
    TaskAssignmentRequest,
    TaskStatusUpdateRequest,
    TaskFilterRequest,
)
from .responses import (
    TaskResponse,
    TaskList,
    TaskStats,
    TaskCountResponse,
)
from .history import (
    TaskHistoryItem,
    TaskDetails,
    EnhancedTaskResponse,
    TaskListResponse,
)

__all__ = [
    "TaskBase",
    "TaskCreate",
    "TaskUpdate",
    "TaskAssignmentRequest",
    "TaskStatusUpdateRequest",
    "TaskFilterRequest",
    "TaskResponse",
    "TaskList",
    "TaskStats",
    "TaskCountResponse",
    "TaskHistoryItem",
    "TaskDetails",
    "EnhancedTaskResponse",
    "TaskListResponse",
]
