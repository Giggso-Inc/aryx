"""
App model for storing available applications
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB

from app.core.database import Base


class App(Base):
    """App model for storing available applications"""
    
    __tablename__ = "gg_apps"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # App information
    app_name = Column(String(255), nullable=False, index=True)
    app_key = Column(String(100), nullable=False, unique=True, index=True)  # Internal unique identifier
    app_description = Column(Text, nullable=True)
    app_image = Column(String(500), nullable=True)  # URL to app image
    
    # App settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=True, nullable=False)
    settings = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # App metadata
    version = Column(String(50), nullable=True)
    category = Column(String(100), nullable=True)
    tags = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_app_name_hash', 'app_name'),
        Index('idx_app_category', 'category'),
        Index('idx_app_active_public', 'is_active', 'is_public'),
        Index('idx_app_version', 'version'),
    )
    
    def __repr__(self):
        return f"<App(id={self.id}, app_name={self.app_name})>"
    
    @property
    def sub_category(self) -> str:
        """Derive sub_category from app_key (Cloud Drive or Datasource)"""
        cloud_drive_keys = ['google_drive', 'googledrive', 'sharepoint', 'share_point', 
                           'dropbox', 'onedrive', 'one_drive', 'box']
        app_key_lower = self.app_key.lower() if self.app_key else ""
        if any(key.lower() == app_key_lower for key in cloud_drive_keys):
            return 'Cloud Drive'
        return 'Datasource'
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": str(self.id),
            "app_name": self.app_name,
            "app_key": self.app_key,
            "app_description": self.app_description,
            "app_image": self.app_image,
            "is_active": self.is_active,
            "is_public": self.is_public,
            "version": self.version,
            "category": self.category,
            "sub_category": self.sub_category,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        } 