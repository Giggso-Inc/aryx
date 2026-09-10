"""GET /{approval_id}/debug and GET /{approval_id}/history — raw metadata and rendered timeline."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval

from .history_access import check_history_access
from .history_timeline_view import build_history_view

router = APIRouter()


@router.get("/{approval_id}/debug", response_model=Dict[str, Any])
async def debug_approval_metadata(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Debug endpoint to check raw approval metadata."""
    user = await get_current_user_required(request, db)

    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    return {
        "approval_id": str(approval.id),
        "status": approval.status,
        "approver_user_id": str(approval.approver_user_id),
        "raw_metadata": approval.approval_metadata,
        "metadata_type": type(approval.approval_metadata).__name__,
        "metadata_keys": list(approval.approval_metadata.keys()) if approval.approval_metadata else [],
        "reassignments_count": len(approval.approval_metadata.get('reassignments', [])) if approval.approval_metadata else 0,
        "status_changes_count": len(approval.approval_metadata.get('status_changes', [])) if approval.approval_metadata else 0
    }


@router.get("/{approval_id}/history", response_model=List[Dict[str, Any]])
async def get_approval_history(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Get comprehensive approval history including all actions and reassignments."""
    user = await get_current_user_required(request, db)

    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    # Check if user has access to this approval (must be requester, approver, or channel member)
    await check_history_access(approval, user, db)

    return build_history_view(approval)
