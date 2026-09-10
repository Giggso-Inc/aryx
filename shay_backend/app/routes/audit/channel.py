"""
GET /channel/{channel_id} -> list_channel_audit_log.

Split from the original 389-line app/routes/audit.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from typing import Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.audit_log import AuditLog
from app.models.channel import Channel

from .helpers import _audit_query, _collect_user_names_for_rows, _rows_to_items
from .models import AuditLogListResponse

router = APIRouter()


@router.get("/channel/{channel_id}", response_model=AuditLogListResponse)
async def list_channel_audit_log(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Query(None, description="Filter by user ID (actor)"),
    action: Optional[str] = Query(None, description="Filter by action e.g. task.assigned"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type e.g. channel, thread"),
    date_from: Optional[datetime] = Query(None, description="Filter from this date (inclusive)"),
    date_to: Optional[datetime] = Query(None, description="Filter to this date (inclusive)"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
) -> AuditLogListResponse:
    """
    List audit log entries for a specific channel (channel-level audit).
    Caller must have access to the channel (same company and channel access).
    """
    user = await get_current_user_required(request)
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid channel_id")
    # Ensure channel exists and user has access
    ch_stmt = select(Channel).where(Channel.id == cid)
    ch_result = await db.execute(ch_stmt)
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to channel")
    # Base query: all audit entries for this channel
    query = select(AuditLog).where(AuditLog.channel_id == cid)
    query = _audit_query(query, user_id, action, resource_type, date_from, date_to)
    count_stmt = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    query = query.order_by(desc(AuditLog.created_at))
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    rows = result.scalars().all()
    related_maps, user_names = await _collect_user_names_for_rows(db, rows)
    items = _rows_to_items(rows, user_names, related_maps)
    return AuditLogListResponse(items=items, total=total, page=page, size=size)
