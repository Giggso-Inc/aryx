"""
Query-filter and row-mapping helpers for the audit route package.

Split from the original 389-line app/routes/audit.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5). User-id
resolution helpers (`_get_user_names`, `_get_related_user_ids_for_audit_rows`,
`_collect_user_names_for_rows`) live in the sibling `related_users.py` to
keep both files under the Raven 150-line style limit.
"""

from typing import Optional

from sqlalchemy.sql import Select

from app.models.audit_log import AuditLog

# Re-exported for backward-compatible imports (e.g. `from .helpers import
# _get_user_names`) and so `app.routes.audit.helpers` still exposes the full
# original helper surface after the split.
from .related_users import (  # noqa: F401
    _get_user_names,
    _get_related_user_ids_for_audit_rows,
    _collect_user_names_for_rows,
)


def _audit_query(
    base_query,
    user_id: Optional[str],
    action: Optional[str],
    resource_type: Optional[str],
    date_from,
    date_to,
) -> Select:
    """Apply optional filters to an audit log query (user_id, action, resource_type, date range)."""
    from uuid import UUID

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


def _rows_to_items(rows, user_names: Optional[dict] = None, related_maps: Optional[dict] = None) -> list:
    """
    Map ORM rows to AuditLogEntry list.
    user_names: user_id (str) -> display name.
    related_maps: {"task": resource_id->assignee_id, "approval": resource_id->approver_id}; used to set related_user_name.
    """
    from uuid import UUID
    from .models import AuditLogEntry

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
