"""Per-row EnhancedApprovalResponse construction shared by both
list_approvals pagination branches (the requested_by-filtered path and the
normal SQL-paginated path used to duplicate this try/except block verbatim).
"""

import traceback
from typing import Any, Dict, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.schemas.approval import ApprovalDetails, ApprovalHistoryItem, EnhancedApprovalResponse

from .details import build_approval_details
from .history_builder import build_approval_history
from .history_context import build_approval_context


async def resolve_approval_details(approval: Approval, db: AsyncSession) -> Tuple[Dict[str, Any], bool]:
    """Refresh + build approval_details for a row, falling back to a basic
    dict (requested_by=None) if building details raises.

    Returns:
        Tuple[Dict[str, Any], bool]: (approval_details, used_fallback)
    """
    try:
        await db.refresh(approval)
        approval_details = await build_approval_details(approval, db)
        return approval_details, False
    except Exception as e:
        print(f"Error building approval details for {approval.id}: {e}")
        print(f"Approval status: {approval.status}")
        print(f"Approval metadata: {approval.approval_metadata}")
        traceback.print_exc()

        approval_details = {
            'approval_name': approval.title,
            'status': approval.status,
            'approver': None,
            'created_by': None,
            'requested_by': None,
            'title': approval.title,
            'description': approval.description,
            'approval_notes': approval.approval_notes,
            'rejection_reason': approval.rejection_reason,
            'comment': approval.comment,
            'created_at': approval.created_at,
            'updated_at': approval.updated_at,
            'approved_at': approval.approved_at,
            'rejected_at': approval.rejected_at,
            'approval_metadata': approval.approval_metadata or {}
        }
        return approval_details, True


async def build_enhanced_approval(approval: Approval, approval_details: Dict[str, Any], db: AsyncSession) -> EnhancedApprovalResponse:
    """Build the full EnhancedApprovalResponse (with history + context) for a
    row whose approval_details resolved successfully.
    """
    approval_history = await build_approval_history(approval, db)
    context = await build_approval_context(approval, db)

    return EnhancedApprovalResponse(
        id=str(approval.id),
        approval_details=ApprovalDetails(**approval_details),
        approval_history=[ApprovalHistoryItem(**item) for item in approval_history],
        context=context
    )


def build_basic_enhanced_approval(approval: Approval, approval_details: Dict[str, Any]) -> EnhancedApprovalResponse:
    """Build a minimal EnhancedApprovalResponse (no history/context) — used
    for the exception-fallback path.
    """
    return EnhancedApprovalResponse(
        id=str(approval.id),
        approval_details=ApprovalDetails(**approval_details),
        approval_history=[],
        context={}
    )
