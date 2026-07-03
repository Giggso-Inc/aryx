"""
EmailAttachment model for email service attachments
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
import uuid

from app.core.database import Base


class EmailAttachment(Base):
    """EmailAttachment model for email service attachments"""
    
    __tablename__ = "gg_email_attachments"
    
    # Primary key
    # Python default for PostgreSQL + Oracle compatibility (no server_default)
    attachment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign keys
    email_id = Column(UUID(as_uuid=True), ForeignKey("gg_emails.email_id"), nullable=True, index=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("gg_threads.id"), nullable=True, index=True)
    message_id = Column(String(255), nullable=True, index=True)
    
    # File information
    filename = Column(String(255), nullable=True)
    storage_type = Column(String(50), nullable=True)
    storage_path = Column(String(500), nullable=True)
    file_url = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)  # Size in bytes
    file_type = Column(String(100), nullable=True)
    provider = Column(String(50), nullable=True)
    original_filename = Column(String(255), nullable=False)
    attachment_type = Column(String(50), nullable=False)
    is_inline = Column(Boolean, default=False, nullable=True)
    content_id = Column(String(255), nullable=True)
    
    # Vault association
    giggso_vault_id = Column(UUID(as_uuid=True), ForeignKey("gg_vault.giggso_vault_id"), nullable=True, index=True)
    attachment_metadata = Column(JSONB, nullable=True)
    
    # Channel, workspace, user, company associations
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id"), nullable=True, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("gg_workspace.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"), nullable=True, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.current_timestamp(), nullable=True, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.current_timestamp(), nullable=True)
    
    # Indexes
    __table_args__ = (
        Index("idx_attachment_company", "company_id"),
        Index("idx_attachment_created_at", "created_at"),
        Index("idx_attachment_provider", "provider"),
        Index("idx_attachment_storage_type", "storage_type"),
        Index("idx_attachment_type", "attachment_type"),
        Index("idx_attachment_user", "user_id"),
        Index("idx_attachment_channel", "channel_id"),
    )
    
    def __repr__(self):
        return f"<EmailAttachment(attachment_id={self.attachment_id}, filename={self.filename}, storage_path={self.storage_path})>"
