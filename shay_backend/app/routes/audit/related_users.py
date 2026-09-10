"""
User-id resolution helpers for the audit route package.

Split out of app/routes/audit/helpers.py (itself split from the original
389-line app/routes/audit.py) to keep both files under the Raven 150-line
style limit — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5.

`_collect_user_names_for_rows` is a NEW helper: the original single-file
audit.py repeated the same ~25-line block (resolve related_maps, collect
all_user_ids from actor/task-assignee/approval-approver/reassigned-approver,
then resolve user_names) verbatim in all three endpoints. It is copied
verbatim into one function so behavior is unchanged; only the duplication
is removed.
"""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task
from app.models.approval import Approval


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


async def _collect_user_names_for_rows(db: AsyncSession, rows: list) -> tuple:
    """
    Resolve related_maps and user_names for a set of audit rows.

    Extracted verbatim from the block repeated in all three original
    endpoints: collect the actor user_id from every row, the resolved
    task-assignee / approval-approver ids, and any approval.reassigned
    new_approver_id, then look up display names for the full set.
    """
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
    return related_maps, user_names
