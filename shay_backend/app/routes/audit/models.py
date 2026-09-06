"""
Pydantic response models for the audit route package.

Split from the original 389-line app/routes/audit.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel


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
