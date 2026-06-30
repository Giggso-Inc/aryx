"""
Attachment model for file upload and management
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
from app.core.database import Base


class Attachment(Base):
    """Attachment model for file upload and management"""
    
    __tablename__ = "gg_attachments"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # File information
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # Local file path or cloud storage path
    file_size = Column(Integer, nullable=False)  # Size in bytes
    mime_type = Column(String(100), nullable=False)
    file_extension = Column(String(20), nullable=False)
    
    # Storage information
    storage_provider = Column(String(50), default="local", nullable=False)  # local, aws, azure, oracle
    storage_url = Column(String(500), nullable=True)  # Public URL for the file
    
    # Association
    message_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    task_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # New field for task attachments
    channel_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # For backward compatibility
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # File metadata
    is_processed = Column(Boolean, default=False, nullable=False)
    processing_status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, failed
    processing_error = Column(Text, nullable=True)
    
    # Security and access
    is_public = Column(Boolean, default=False, nullable=False)
    access_token = Column(String(255), nullable=True, unique=True)
    
    # File content analysis
    content_summary = Column(Text, nullable=True)
    log_entries_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)
    warning_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Dialect-agnostic indexes
    __table_args__ = (
        Index('idx_attachment_filename_hash', 'filename'),
        Index('idx_attachment_message_time', 'message_id', 'created_at'),
        Index('idx_attachment_task_time', 'task_id', 'created_at'),  # New index for task attachments
        Index('idx_attachment_channel_time', 'channel_id', 'created_at'),
        Index('idx_attachment_user_time', 'user_id', 'created_at'),
        Index('idx_attachment_processing_status', 'processing_status', 'created_at'),
        Index('idx_attachment_file_extension', 'file_extension'),
        Index('idx_attachment_storage_provider', 'storage_provider'),
        Index('idx_attachment_public_time', 'is_public', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Attachment(id={self.id}, filename={self.filename}, size={self.file_size})>"
    
    @property
    def is_task_attachment(self) -> bool:
        """Check if attachment is associated with a task"""
        return self.task_id is not None
    
    @property
    def is_log_file(self) -> bool:
        """Check if file is a log file"""
        return self.file_extension.lower() in [".log", ".txt"]
    
    @property
    def is_json_file(self) -> bool:
        """Check if file is a JSON file"""
        return self.file_extension.lower() == ".json"
    
    @property
    def is_xml_file(self) -> bool:
        """Check if file is an XML file"""
        return self.file_extension.lower() == ".xml"
    
    @property
    def size_mb(self) -> float:
        """Get file size in MB"""
        return self.file_size / (1024 * 1024)
    
    @property
    def is_processed_successfully(self) -> bool:
        """Check if file was processed successfully"""
        return self.is_processed and self.processing_status == "completed"
    
    @property
    def has_errors(self) -> bool:
        """Check if file has processing errors"""
        return self.processing_status == "failed" or self.processing_error is not None
    
    def get_download_url(self, base_url: str) -> str:
        """Get download URL for the file"""
        return f"{base_url}/api/v1/attachments/{self.id}/download"
    
    def can_be_accessed_by_user(self, user_id: str, user_role: str) -> bool:
        """Check if user can access this attachment"""
        if user_role == "admin":
            return True
        return str(self.user_id) == user_id or self.is_public 