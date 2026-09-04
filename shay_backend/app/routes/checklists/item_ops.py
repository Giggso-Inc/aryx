"""
Checklist-item-scoped endpoints (mounted at /api/v1/checklists):
  GET    /checklist/{checklist_id}           get_checklist
  PUT    /checklist/{checklist_id}           update_checklist
  DELETE /checklist/{checklist_id}           delete_checklist
  POST   /checklist/{checklist_id}/complete  toggle_checklist_completion
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.checklist import (
    ChecklistCompletionRequest,
    ChecklistResponse,
    ChecklistUpdate,
)

from .helpers import get_checklist_with_access

router = APIRouter()


@router.get("/checklist/{checklist_id}", response_model=ChecklistResponse)
async def get_checklist(
    checklist_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChecklistResponse:
    """Get a specific checklist item"""
    user = await get_current_user_required(request)
    return await get_checklist_with_access(checklist_id, db, user)


@router.put("/checklist/{checklist_id}", response_model=ChecklistResponse)
async def update_checklist(
    checklist_id: str,
    checklist_data: ChecklistUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChecklistResponse:
    """Update a checklist item"""
    user = await get_current_user_required(request)
    checklist = await get_checklist_with_access(checklist_id, db, user)

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
) -> dict:
    """Delete a checklist item"""
    user = await get_current_user_required(request)
    checklist = await get_checklist_with_access(checklist_id, db, user)

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
) -> ChecklistResponse:
    """Mark checklist as complete or incomplete"""
    user = await get_current_user_required(request)
    checklist = await get_checklist_with_access(checklist_id, db, user)

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
