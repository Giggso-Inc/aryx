"""
Audit service: write audit log entries for assign/reassign and other actions.
"""

from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
import uuid


async def log(
    db: AsyncSession,
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    details: Optional[Dict[str, Any]] = None,
    channel_id: Optional[UUID] = None,
    thread_id: Optional[UUID] = None,
) -> None:
    """
    Append one audit log row. Does not commit; caller should commit.
    """
    entry = AuditLog(
        id=uuid.uuid4(),
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        channel_id=channel_id,
        thread_id=thread_id,
        details=details or {},
    )
    db.add(entry)
    await db.flush()
