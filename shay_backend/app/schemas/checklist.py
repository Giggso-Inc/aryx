"""
Checklist schemas for request/response validation

This module defines Pydantic schemas for checklist management including creation,
updates, responses, and validation rules.

File: app/schemas/checklist.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Checklist item validation with text and ordering
- Bulk operations for multiple checklist items
- Completion tracking and reordering support
- Metadata and statistics support
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID


class ChecklistBase(BaseModel):
    """Base schema for Checklist"""
    text: str = Field(..., min_length=1, max_length=500, description="Checklist item text")
    order_index: int = Field(..., ge=0, description="Order index for maintaining sequence")
    checklist_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional checklist metadata")


class ChecklistCreate(ChecklistBase):
    """Schema for creating a new checklist item"""
    pass


class ChecklistUpdate(BaseModel):
    """Schema for updating a checklist item"""
    text: Optional[str] = Field(None, min_length=1, max_length=500)
    order_index: Optional[int] = Field(None, ge=0)
    checklist_metadata: Optional[Dict[str, Any]] = None


class ChecklistResponse(ChecklistBase):
    """Schema for checklist response"""
    id: Union[str, UUID]
    task_id: Union[str, UUID]
    is_completed: bool
    completed_at: Optional[datetime] = None
    completed_by: Optional[Union[str, UUID]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChecklistList(BaseModel):
    """Schema for checklist list response"""
    checklists: List[ChecklistResponse]
    total: int
    completed_count: int
    incomplete_count: int


class ChecklistBulkCreate(BaseModel):
    """Schema for creating multiple checklist items at once"""
    checklists: List[ChecklistCreate] = Field(..., min_items=1, max_items=100)


class ChecklistBulkUpdate(BaseModel):
    """Schema for updating multiple checklist items at once"""
    checklists: List[Dict[str, Any]] = Field(..., min_items=1, max_items=100)
    # Each item should have: {"id": "uuid", "text": "new text", "order_index": 1, etc.}


class ChecklistCompletionRequest(BaseModel):
    """Schema for marking checklist as complete/incomplete"""
    is_completed: bool = Field(..., description="Whether to mark as completed or incomplete")
    comments: Optional[str] = Field(None, description="Optional comments for completion")


class ChecklistReorderRequest(BaseModel):
    """Schema for reordering checklist items"""
    checklist_orders: List[Dict[str, Any]] = Field(..., min_items=1)
    # Each item should have: {"checklist_id": "uuid", "new_order": new_order}


class ChecklistStats(BaseModel):
    """Schema for checklist statistics"""
    total_items: int
    completed_items: int
    incomplete_items: int
    completion_percentage: float
    last_completed_at: Optional[datetime] = None
