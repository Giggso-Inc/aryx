"""
Datasource model for managing data sources from various platforms
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Index, JSON, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class Datasource(Base):
    """Datasource model for managing data sources from various platforms"""
    
    __tablename__ = "gg_datasources"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Basic information
    name = Column(String(255), nullable=False, index=True)
    filename = Column(String(500), nullable=False, index=True)
    
    # Storage type and configuration
    storage_type = Column(String(50), nullable=False, index=True)  # local, cloud, app
    provider = Column(String(100), nullable=True)  # s3, azure, googleDrive, sharePoint, etc.
    app_type = Column(String(100), nullable=True)  # googleDrive, sharePoint, etc.
    
    # Configuration (JSONB for flexible storage)
    config = Column(JSONB, nullable=True)
    
    # Metadata for additional information
    datasource_metadata = Column(JSONB, nullable=True)
    
    # Vault integration
    giggso_vault_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Reference to gg_vault table
    
    # File information
    file_size = Column(Integer, nullable=True)
    file_type = Column(String(255), nullable=True)
    file_url = Column(String(1000), nullable=True)
    log_type = Column(String(100), nullable=True, index=True)  # android, kubernetes, python, etc.
    
    # Channel association (workspace_id and company_id can be obtained from channel)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id"), nullable=False, index=True)
    
    # User who added the datasource
    added_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Status and metadata
    is_active = Column(Boolean, default=True, nullable=False)
    is_connected = Column(Boolean, default=True, nullable=False)  # Connection state at topic level
    is_processed = Column(Boolean, default=False, nullable=False)
    processing_status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)
    
    # Embedding related fields
    is_embedding_required = Column(Boolean, default=False, nullable=False)  # Whether embedding is required for this datasource
    embedding_status = Column(Integer, default=0, nullable=False)  # 0=not required, 1=in progress, 2=completed, 3=failed
    
    # Processing metadata
    last_processed_at = Column(DateTime, nullable=True)
    processing_time = Column(Integer, nullable=True)  # in milliseconds
    record_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationship
    channel = relationship("Channel", backref="datasources")
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_datasource_name_hash', 'name'),
        Index('idx_datasource_storage_type', 'storage_type'),
        Index('idx_datasource_provider', 'provider'),
        Index('idx_datasource_channel_time', 'channel_id', 'created_at'),
        Index('idx_datasource_status', 'processing_status'),
        Index('idx_datasource_active', 'is_active'),
        Index('idx_datasource_connected', 'is_connected'),
        Index('idx_datasource_processed', 'is_processed'),
        Index('idx_datasource_embedding_status', 'embedding_status'),
    )
    
    def __repr__(self):
        return f"<Datasource(id={self.id}, name={self.name}, storage_type={self.storage_type})>"
    
    def is_accessible_by_user(self, user_company_id: str, user_role: str) -> bool:
        """Check if datasource is accessible by user"""
        # Datasource is accessible if user belongs to same company as the channel
        # This will be checked via channel relationship in the route
        return True  # Will be validated in route via channel access
    
    def get_storage_info(self) -> dict:
        """Get storage information based on type"""
        if self.storage_type == "local":
            return {
                "type": "local",
                "filename": self.filename,
                "file_url": self.file_url
            }
        elif self.storage_type == "cloud":
            return {
                "type": "cloud",
                "provider": self.provider,
                "config": self.config or {},
                "file_url": self.file_url
            }
        elif self.storage_type == "app":
            return {
                "type": "app",
                "app_type": self.app_type,
                "config": self.config or {},
                "file_url": self.file_url
            }
        return {}
    
    def get_filename_with_user_date(self, user_id: str) -> str:
        """Generate filename with user ID and current date"""
        from datetime import datetime
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.filename}_{user_id}_{current_date}.{self.file_type or 'txt'}"
    
    def mark_processing_started(self):
        """Mark datasource as processing started"""
        self.processing_status = "processing"
        self.updated_at = datetime.utcnow()
    
    def mark_processing_completed(self, record_count: int = 0, processing_time: int = 0):
        """Mark datasource as processing completed"""
        self.processing_status = "completed"
        self.is_processed = True
        self.record_count = record_count
        self.processing_time = processing_time
        self.last_processed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def mark_processing_failed(self, error_message: str):
        """Mark datasource as processing failed"""
        self.processing_status = "failed"
        self.error_message = error_message
        self.updated_at = datetime.utcnow() 