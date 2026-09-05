"""
Shared base task schema and validators.

File: app/schemas/task/base.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Split out of the former app/schemas/task.py to keep each file under the
Raven 150-line style limit. Contains only the shared TaskBase schema and
its field validators (status, source, priority, due_date parsing).
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
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
    def validate_status(cls, v) -> str:
        """Validate task status values for base task"""
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
        """Validate task priority values"""
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
