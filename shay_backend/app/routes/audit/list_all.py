"""
GET "" -> list_audit_log.

Split from the original 389-line app/routes/audit.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.audit_log import AuditLog
from app.models.channel import Channel

from .helpers import _collect_user_names_for_rows, _rows_to_items
from .models import AuditLogListResponse

router = APIRouter()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    thread_id: Optional[str] = Query(None, description="Filter by thread ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID (actor)"),
    action: Optional[str] = Query(None, description="Filter by action e.g. task.assigned"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type e.g. channel, thread"),
    date_from: Optional[datetime] = Query(None, description="Filter from this date (inclusive)"),
    date_to: Optional[datetime] = Query(None, description="Filter to this date (inclusive)"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
) -> AuditLogListResponse:
    """
    List audit log entries for the current user's company.
    Results are restricted to channels belonging to the user's company.
    """
    # Require auth and scope to current user's company
    user = await get_current_user_required(request)

    # Restrict to audit entries whose channel belongs to user's company
    channel_ids_subq = select(Channel.id).where(Channel.company_id == user.company_id)
    query = (
        select(AuditLog)
        .where(AuditLog.channel_id.in_(channel_ids_subq))
    )

    # Apply optional filters from query params
    from uuid import UUID

    if channel_id:
        try:
            cid = UUID(channel_id)
            query = query.where(AuditLog.channel_id == cid)
        except ValueError:
            pass
    if thread_id:
        try:
            tid = UUID(thread_id)
            query = query.where(AuditLog.thread_id == tid)
        except ValueError:
            pass
    if user_id:
        try:
            uid = UUID(user_id)
            query = query.where(AuditLog.user_id == uid)
        except ValueError:
            pass
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if date_from is not None:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.where(AuditLog.created_at <= date_to)

    # Count total matching rows (same filters, no order/limit/offset)
    count_stmt = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Sort newest first and paginate
    query = query.order_by(desc(AuditLog.created_at))
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    rows = result.scalars().all()
    related_maps, user_names = await _collect_user_names_for_rows(db, rows)
    items = _rows_to_items(rows, user_names, related_maps)
    return AuditLogListResponse(items=items, total=total, page=page, size=size)
