"""
Audit log model for channel/thread and task/approval assign-reassign actions.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.db_types import UUID, JSONB


class AuditLog(Base):
    """Audit log for who did what, when (channel, thread, task, approval)."""

    __tablename__ = "gg_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # Actor who performed the action
    action = Column(String(80), nullable=False, index=True)  # e.g. task.assigned, approval.reassigned
    resource_type = Column(String(40), nullable=False, index=True)  # channel, thread, task, approval
    resource_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    channel_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    thread_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    details = Column(JSONB, nullable=True)  # e.g. old_assignee_id, new_assignee_id
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    __table_args__ = (
        Index("idx_audit_log_channel", "channel_id"),
        Index("idx_audit_log_thread", "thread_id"),
        Index("idx_audit_log_created", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, resource_type={self.resource_type})>"
