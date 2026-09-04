"""
Task-scoped checklist reorder/stats endpoints (mounted at /api/v1/checklists):
  POST /task/{task_id}/checklists/reorder   reorder_checklists
  GET  /task/{task_id}/checklists/stats     get_checklist_stats

CRUD endpoints for this same resource live in ./task_ops.py — split by
function, not by convenience, to keep both files under the 150-line target
(the original single file covering all five was 208 lines).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.checklist import Checklist
from app.schemas.checklist import ChecklistList, ChecklistReorderRequest, ChecklistStats

from .helpers import get_task_with_workspace_access
from .task_ops import get_task_checklists

router = APIRouter()


@router.post("/task/{task_id}/checklists/reorder", response_model=ChecklistList)
async def reorder_checklists(
    task_id: str,
    reorder_data: ChecklistReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChecklistList:
    """Reorder checklist items for a task"""
    user = await get_current_user_required(request)
    await get_task_with_workspace_access(task_id, db, user)

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
) -> ChecklistStats:
    """Get checklist statistics for a task"""
    user = await get_current_user_required(request)
    await get_task_with_workspace_access(task_id, db, user)

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
