"""
GGEmail model — stores emails ingested from external providers (Gmail, Microsoft, etc.)
"""

from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID
import uuid

from app.core.database import Base


class GGEmail(Base):
    __tablename__ = "gg_emails"

    # Primary key
    email_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Thread linkage — managed by messages.py cleanup SQL
    thread_id = Column(UUID(as_uuid=True), ForeignKey("gg_threads.id"), nullable=True)

    # External email identity
    message_id = Column(String(500), nullable=True)
    sender = Column(String(500), nullable=True)
    recipient = Column(Text, nullable=True)
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    provider = Column(String(50), nullable=True)  # gmail, microsoft, etc.

    # ML pipeline state
    # thread_created stays True after thread creation so the scheduler skips re-processing
    thread_created = Column(Boolean, default=False, nullable=True)
    ml_processed_at = Column(DateTime, nullable=True)

    # Timestamps
    received_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.current_timestamp(), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.current_timestamp(), nullable=True)

    # Tenant associations
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("gg_workspace.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=True)

    __table_args__ = (
        Index("idx_gg_emails_thread", "thread_id"),
        Index("idx_gg_emails_company", "company_id"),
        Index("idx_gg_emails_message_id", "message_id"),
        Index("idx_gg_emails_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<GGEmail(email_id={self.email_id}, sender={self.sender}, subject={self.subject})>"
