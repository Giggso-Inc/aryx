"""
Checklist routes for managing task checklists

This module defines FastAPI routes for comprehensive checklist management including
creation, updates, completion tracking, and reordering.

File: app/routes/checklists.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Bulk checklist creation and management
- Individual checklist operations
- Completion tracking with user attribution
- Dynamic reordering of checklist items
- Comprehensive access control and validation
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.task import Task
from app.models.checklist import Checklist
from app.models.workspace import Workspace
from app.schemas.checklist import (
    ChecklistCreate,
    ChecklistUpdate,
    ChecklistResponse,
    ChecklistList,
    ChecklistBulkCreate,
    ChecklistBulkUpdate,
    ChecklistCompletionRequest,
    ChecklistReorderRequest,
    ChecklistStats
)

router = APIRouter()


@router.post("/task/{task_id}/checklists", response_model=ChecklistList)
async def create_task_checklists(
    task_id: str,
    checklist_data: ChecklistBulkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create multiple checklist items for a task"""
    user = await get_current_user_required(request)
    
    # Get task and verify access
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access through workspace
    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )
    
    # Get current max order index
    max_order_stmt = select(func.max(Checklist.order_index)).where(Checklist.task_id == task_id)
    max_order_result = await db.execute(max_order_stmt)
    max_order = max_order_result.scalar() or -1
    
    # Create checklist items
    checklists = []
    for i, checklist_item in enumerate(checklist_data.checklists):
        # Auto-assign order index if not provided
        if checklist_item.order_index is None:
            checklist_item.order_index = max_order + i + 1
        
        checklist = Checklist(
            id=str(uuid.uuid4()),
            task_id=task_id,
            text=checklist_item.text,
            order_index=checklist_item.order_index,
            checklist_metadata=checklist_item.checklist_metadata
        )
        
        checklists.append(checklist)
        db.add(checklist)
    
    await db.commit()
    
    # Refresh and return all checklists for the task
    return await get_task_checklists(task_id, request, db)


@router.get("/task/{task_id}/checklists", response_model=ChecklistList)
async def get_task_checklists(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get all checklist items for a task"""
    user = await get_current_user_required(request)
    
    # Get task and verify access
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access through workspace
    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )
    
    # Get checklists ordered by order_index
    checklist_stmt = select(Checklist).where(Checklist.task_id == task_id).order_by(Checklist.order_index)
    checklist_result = await db.execute(checklist_stmt)
    checklists = checklist_result.scalars().all()
    
    # Calculate counts
    total = len(checklists)
    completed_count = len([c for c in checklists if c.is_completed])
    incomplete_count = total - completed_count
    
    return ChecklistList(
        checklists=checklists,
        total=total,
        completed_count=completed_count,
        incomplete_count=incomplete_count
    )


@router.get("/checklist/{checklist_id}", response_model=ChecklistResponse)
async def get_checklist(
    checklist_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific checklist item"""
    user = await get_current_user_required(request)
    
    # Get checklist
    checklist_stmt = select(Checklist).where(Checklist.id == checklist_id)
    result = await db.execute(checklist_stmt)
    checklist = result.scalar_one_or_none()
    
    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found"
        )
    
    # Check access through task and workspace
    task_stmt = select(Task).where(Task.id == checklist.task_id)
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()
    
    if task and task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to checklist"
            )
    
    return checklist


@router.put("/checklist/{checklist_id}", response_model=ChecklistResponse)
async def update_checklist(
    checklist_id: str,
    checklist_data: ChecklistUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a checklist item"""
    user = await get_current_user_required(request)
    
    # Get checklist
    checklist_stmt = select(Checklist).where(Checklist.id == checklist_id)
    result = await db.execute(checklist_stmt)
    checklist = result.scalar_one_or_none()
    
    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found"
        )
    
    # Check access through task and workspace
    task_stmt = select(Task).where(Task.id == checklist.task_id)
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()
    
    if task and task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to checklist"
            )
    
    # Update fields
    update_data = checklist_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(checklist, field):
            setattr(checklist, field, value)
    
    checklist.updated_at = datetime.now()
    
    await db.commit()
    await db.refresh(checklist)
    
    return checklist


@router.delete("/checklist/{checklist_id}")
async def delete_checklist(
    checklist_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete a checklist item"""
    user = await get_current_user_required(request)
    
    # Get checklist
    checklist_stmt = select(Checklist).where(Checklist.id == checklist_id)
    result = await db.execute(checklist_stmt)
    checklist = result.scalar_one_or_none()
    
    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found"
        )
    
    # Check access through task and workspace
    task_stmt = select(Task).where(Task.id == checklist.task_id)
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()
    
    if task and task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to checklist"
            )
    
    # Delete checklist
    await db.delete(checklist)
    await db.commit()
    
    return {"message": "Checklist deleted successfully"}


@router.post("/checklist/{checklist_id}/complete", response_model=ChecklistResponse)
async def toggle_checklist_completion(
    checklist_id: str,
    completion_data: ChecklistCompletionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Mark checklist as complete or incomplete"""
    user = await get_current_user_required(request)
    
    # Get checklist
    checklist_stmt = select(Checklist).where(Checklist.id == checklist_id)
    result = await db.execute(checklist_stmt)
    checklist = result.scalar_one_or_none()
    
    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found"
        )
    
    # Check access through task and workspace
    task_stmt = select(Task).where(Task.id == checklist.task_id)
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()
    
    if task and task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to checklist"
            )
    
    # Toggle completion
    if completion_data.is_completed:
        checklist.mark_completed(str(user.id))
    else:
        checklist.mark_incomplete()
    
    # Add comments to metadata if provided
    if completion_data.comments:
        if not checklist.checklist_metadata:
            checklist.checklist_metadata = {}
        
        if 'completion_comments' not in checklist.checklist_metadata:
            checklist.checklist_metadata['completion_comments'] = []
        
        checklist.checklist_metadata['completion_comments'].append({
            'comment': completion_data.comments,
            'user_id': str(user.id),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': 'completed' if completion_data.is_completed else 'marked_incomplete'
        })
    
    await db.commit()
    await db.refresh(checklist)
    
    return checklist


@router.post("/task/{task_id}/checklists/reorder", response_model=ChecklistList)
async def reorder_checklists(
    task_id: str,
    reorder_data: ChecklistReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Reorder checklist items for a task"""
    user = await get_current_user_required(request)
    
    # Get task and verify access
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access through workspace
    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )
    
    # Update order for each checklist
    for item in reorder_data.checklist_orders:
        checklist_id = item.get('checklist_id')
        new_order = item.get('new_order')
        
        if checklist_id and new_order is not None:
            checklist_stmt = select(Checklist).where(
                and_(Checklist.id == checklist_id, Checklist.task_id == task_id)
            )
            checklist_result = await db.execute(checklist_stmt)
            checklist = checklist_result.scalar_one_or_none()
            
            if checklist:
                checklist.order_index = new_order
                checklist.updated_at = datetime.now()
    
    await db.commit()
    
    # Return updated checklist list
    return await get_task_checklists(task_id, request, db)


@router.get("/task/{task_id}/checklists/stats", response_model=ChecklistStats)
async def get_checklist_stats(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get checklist statistics for a task"""
    user = await get_current_user_required(request)
    
    # Get task and verify access
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access through workspace
    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )
    
    # Get checklist stats
    total_stmt = select(func.count(Checklist.id)).where(Checklist.task_id == task_id)
    total_result = await db.execute(total_stmt)
    total_items = total_result.scalar()
    
    completed_stmt = select(func.count(Checklist.id)).where(
        and_(Checklist.task_id == task_id, Checklist.is_completed == True)
    )
    completed_result = await db.execute(completed_stmt)
    completed_items = completed_result.scalar()
    
    incomplete_items = total_items - completed_items
    
    # Calculate completion percentage
    completion_percentage = (completed_items / total_items * 100) if total_items > 0 else 0.0
    
    # Get last completed timestamp
    last_completed_stmt = select(Checklist.completed_at).where(
        and_(Checklist.task_id == task_id, Checklist.is_completed == True)
    ).order_by(desc(Checklist.completed_at)).limit(1)
    last_completed_result = await db.execute(last_completed_stmt)
    last_completed_at = last_completed_result.scalar()
    
    return ChecklistStats(
        total_items=total_items,
        completed_items=completed_items,
        incomplete_items=incomplete_items,
        completion_percentage=round(completion_percentage, 2),
        last_completed_at=last_completed_at
    )


@router.post("/task/{task_id}/checklists/add", response_model=ChecklistResponse)
async def add_single_checklist(
    task_id: str,
    checklist_data: ChecklistCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Add a single checklist item to a task"""
    user = await get_current_user_required(request)
    
    # Get task and verify access
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access through workspace
    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )
    
    # Auto-assign order index if not provided
    if checklist_data.order_index is None:
        max_order_stmt = select(func.max(Checklist.order_index)).where(Checklist.task_id == task_id)
        max_order_result = await db.execute(max_order_stmt)
        max_order = max_order_result.scalar() or -1
        checklist_data.order_index = max_order + 1
    
    # Create checklist
    checklist = Checklist(
        id=str(uuid.uuid4()),
        task_id=task_id,
        text=checklist_data.text,
        order_index=checklist_data.order_index,
        checklist_metadata=checklist_data.checklist_metadata
    )
    
    db.add(checklist)
    await db.commit()
    await db.refresh(checklist)
    
    return checklist
