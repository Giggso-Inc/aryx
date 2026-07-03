"""
Audit log list/filter API. Returns audit entries scoped to the current user's company.
"""

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from pydantic import BaseModel

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.audit_log import AuditLog
from app.models.channel import Channel
from app.models.user import User
from app.models.task import Task
from app.models.approval import Approval


router = APIRouter()


def _audit_query(
    base_query,
    user_id: Optional[str],
    action: Optional[str],
    resource_type: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    """Apply optional filters to an audit log query (user_id, action, resource_type, date range)."""
    if user_id:
        try:
            uid = UUID(user_id)
            base_query = base_query.where(AuditLog.user_id == uid)
        except ValueError:
            pass
    if action:
        base_query = base_query.where(AuditLog.action == action)
    if resource_type:
        base_query = base_query.where(AuditLog.resource_type == resource_type)
    if date_from is not None:
        base_query = base_query.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        base_query = base_query.where(AuditLog.created_at <= date_to)
    return base_query


async def _get_user_names(db: AsyncSession, user_ids: List[UUID]) -> dict:
    """Fetch user names for given user IDs; returns dict mapping user_id (str) -> name (or email fallback)."""
    if not user_ids:
        return {}
    stmt = select(User.id, User.name, User.email_id).where(User.id.in_(user_ids))
    result = await db.execute(stmt)
    rows = result.all()
    return {
        str(r.id): (r.name if r.name else (r.email_id or "Unknown")) for r in rows
    }


async def _get_related_user_ids_for_audit_rows(db: AsyncSession, rows: list) -> dict:
    """
    For task/approval audit rows, resolve the "related" user (assignee for task, approver for approval).
    Returns dict mapping audit row index or (resource_type, resource_id) -> user_id (str) for lookup.
    We return a list of (row_index, related_user_id_str) so we can attach to the right row.
    Actually simpler: return a dict (resource_type, resource_id) -> user_id (str), but for approval
    reassigned we need details.new_approver_id so we handle that per-row. So we return:
    - task_assignee_map: resource_id (str) -> user_id (str)
    - approval_approver_map: resource_id (str) -> user_id (str)
    Then when building items we use for task: task_assignee_map.get(str(r.resource_id)); for approval:
    details.get("new_approver_id") if action reassigned else approval_approver_map.get(str(r.resource_id)).
    """
    task_ids = list({r.resource_id for r in rows if r.resource_type == "task"})
    approval_ids = list({r.resource_id for r in rows if r.resource_type == "approval"})
    task_assignee_map = {}
    approval_approver_map = {}
    if task_ids:
        stmt = select(Task.id, Task.assigned_to).where(Task.id.in_(task_ids))
        result = await db.execute(stmt)
        for r in result.all():
            if r.assigned_to:
                task_assignee_map[str(r.id)] = str(r.assigned_to)
    if approval_ids:
        stmt = select(Approval.id, Approval.approver_user_id).where(Approval.id.in_(approval_ids))
        result = await db.execute(stmt)
        for r in result.all():
            if r.approver_user_id:
                approval_approver_map[str(r.id)] = str(r.approver_user_id)
    return {"task": task_assignee_map, "approval": approval_approver_map}


def _rows_to_items(rows, user_names: Optional[dict] = None, related_maps: Optional[dict] = None):
    """
    Map ORM rows to AuditLogEntry list.
    user_names: user_id (str) -> display name.
    related_maps: {"task": resource_id->assignee_id, "approval": resource_id->approver_id}; used to set related_user_name.
    """
    user_names = user_names or {}
    related_maps = related_maps or {}
    task_map = related_maps.get("task") or {}
    approval_map = related_maps.get("approval") or {}
    items = []
    for r in rows:
        related_user_id = None
        if r.resource_type == "task":
            related_user_id = task_map.get(str(r.resource_id)) or (r.details or {}).get("assignee_id")
        elif r.resource_type == "approval":
            details = r.details or {}
            if r.action == "approval.reassigned" and details.get("new_approver_id"):
                related_user_id = details.get("new_approver_id")
            else:
                related_user_id = approval_map.get(str(r.resource_id))
        if related_user_id and isinstance(related_user_id, UUID):
            related_user_id = str(related_user_id)
        related_user_name = user_names.get(related_user_id) if related_user_id else None
        items.append(
            AuditLogEntry(
                id=str(r.id),
                user_id=str(r.user_id),
                user_name=user_names.get(str(r.user_id)),
                action=r.action,
                resource_type=r.resource_type,
                resource_id=str(r.resource_id),
                channel_id=str(r.channel_id) if r.channel_id else None,
                thread_id=str(r.thread_id) if r.thread_id else None,
                details=r.details if isinstance(r.details, dict) else None,
                created_at=r.created_at,
                related_user_id=related_user_id,
                related_user_name=related_user_name,
            )
        )
    return items


class AuditLogEntry(BaseModel):
    """Single audit log entry for API response."""
    id: str
    user_id: str
    user_name: Optional[str] = None  # Actor: resolved from User by user_id (name or email)
    action: str
    resource_type: str
    resource_id: str
    channel_id: Optional[str] = None
    thread_id: Optional[str] = None
    details: Optional[dict] = None
    created_at: datetime
    # For task: assignee; for approval: approver (or new approver when reassigned)
    related_user_id: Optional[str] = None
    related_user_name: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated list of audit log entries."""
    items: List[AuditLogEntry]
    total: int
    page: int
    size: int


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
):
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
    related_maps = await _get_related_user_ids_for_audit_rows(db, rows)
    all_user_ids = list({r.user_id for r in rows})
    for uid in (related_maps.get("task") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for uid in (related_maps.get("approval") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for r in rows:
        if r.resource_type == "approval" and r.action == "approval.reassigned":
            uid = (r.details or {}).get("new_approver_id")
            if uid:
                try:
                    all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
                except (ValueError, TypeError):
                    pass
    user_names = await _get_user_names(db, list(set(all_user_ids)))
    items = _rows_to_items(rows, user_names, related_maps)
    return AuditLogListResponse(items=items, total=total, page=page, size=size)


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
):
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
    related_maps = await _get_related_user_ids_for_audit_rows(db, rows)
    all_user_ids = list({r.user_id for r in rows})
    for uid in (related_maps.get("task") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for uid in (related_maps.get("approval") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for r in rows:
        if r.resource_type == "approval" and r.action == "approval.reassigned":
            uid = (r.details or {}).get("new_approver_id")
            if uid:
                try:
                    all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
                except (ValueError, TypeError):
                    pass
    user_names = await _get_user_names(db, list(set(all_user_ids)))
    items = _rows_to_items(rows, user_names, related_maps)
    return AuditLogListResponse(items=items, total=total, page=page, size=size)


@router.get("/channel/{channel_id}/thread/{thread_id}", response_model=AuditLogListResponse)
async def list_thread_audit_log(
    channel_id: str,
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Query(None, description="Filter by user ID (actor)"),
    action: Optional[str] = Query(None, description="Filter by action e.g. task.assigned"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type e.g. channel, thread"),
    date_from: Optional[datetime] = Query(None, description="Filter from this date (inclusive)"),
    date_to: Optional[datetime] = Query(None, description="Filter to this date (inclusive)"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
):
    """
    List audit log entries for a specific thread within a channel (thread-level audit).
    Caller must have access to the channel (same company and channel access).
    """
    user = await get_current_user_required(request)
    try:
        cid = UUID(channel_id)
        tid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid channel_id or thread_id")
    # Ensure channel exists and user has access
    ch_stmt = select(Channel).where(Channel.id == cid)
    ch_result = await db.execute(ch_stmt)
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to channel")
    # Base query: audit entries for this channel and thread
    query = select(AuditLog).where(AuditLog.channel_id == cid, AuditLog.thread_id == tid)
    query = _audit_query(query, user_id, action, resource_type, date_from, date_to)
    count_stmt = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    query = query.order_by(desc(AuditLog.created_at))
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    rows = result.scalars().all()
    related_maps = await _get_related_user_ids_for_audit_rows(db, rows)
    all_user_ids = list({r.user_id for r in rows})
    for uid in (related_maps.get("task") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for uid in (related_maps.get("approval") or {}).values():
        try:
            all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
        except (ValueError, TypeError):
            pass
    for r in rows:
        if r.resource_type == "approval" and r.action == "approval.reassigned":
            uid = (r.details or {}).get("new_approver_id")
            if uid:
                try:
                    all_user_ids.append(UUID(uid) if isinstance(uid, str) else uid)
                except (ValueError, TypeError):
                    pass
    user_names = await _get_user_names(db, list(set(all_user_ids)))
    items = _rows_to_items(rows, user_names, related_maps)
    return AuditLogListResponse(items=items, total=total, page=page, size=size)
