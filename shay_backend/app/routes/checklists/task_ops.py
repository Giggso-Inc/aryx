"""
Task-scoped checklist CRUD endpoints (mounted at /api/v1/checklists):
  POST /task/{task_id}/checklists       create_task_checklists
  GET  /task/{task_id}/checklists       get_task_checklists
  POST /task/{task_id}/checklists/add   add_single_checklist

Reorder/stats endpoints for this same resource live in ./task_meta.py —
split by function, not by convenience, to keep both files under the
150-line target (the original single file covering all five was 208 lines).
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.checklist import Checklist
from app.schemas.checklist import ChecklistBulkCreate, ChecklistCreate, ChecklistList, ChecklistResponse

from .helpers import get_task_with_workspace_access

router = APIRouter()


@router.post("/task/{task_id}/checklists", response_model=ChecklistList)
async def create_task_checklists(
    task_id: str,
    checklist_data: ChecklistBulkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChecklistList:
    """Create multiple checklist items for a task"""
    user = await get_current_user_required(request)
    await get_task_with_workspace_access(task_id, db, user)

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
) -> ChecklistList:
    """Get all checklist items for a task"""
    user = await get_current_user_required(request)
    await get_task_with_workspace_access(task_id, db, user)

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


@router.post("/task/{task_id}/checklists/add", response_model=ChecklistResponse)
async def add_single_checklist(
    task_id: str,
    checklist_data: ChecklistCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChecklistResponse:
    """Add a single checklist item to a task"""
    user = await get_current_user_required(request)
    await get_task_with_workspace_access(task_id, db, user)

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
