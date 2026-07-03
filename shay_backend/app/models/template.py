"""
Template model for storing email template details.

This module defines the SQLAlchemy ORM model for email templates, including all template-related
fields for storing template metadata and configuration.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0
"""

# Standard library imports for date/time operations and UUID
import uuid
from datetime import datetime

# SQLAlchemy core components for table definition and column types
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB

# Base class for SQLAlchemy declarative models
from app.core.database import Base


class Template(Base):
    """Template model for storing email template details"""
    
    __tablename__ = "gg_templates"
    
    # Primary key - UUID (Python default for PostgreSQL + Oracle compatibility)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Template identifier - auto-generated format TMPLT_INVITE_001
    template_id = Column(String(255), nullable=False, unique=True, index=True)
    
    # Template name (file name)
    template_name = Column(String(500), nullable=False, index=True)
    
    # File path for storage
    file_path = Column(String(500), nullable=True)
    
    # File size
    file_size = Column(String(50), nullable=True)
    
    # Additional configuration stored as JSON
    additional_config = Column(JSONB, nullable=True, default={})
    
    # Timestamps
    created_datetime = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_datetime = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_template_id', 'template_id'),
        Index('idx_template_name', 'template_name'),
        Index('idx_created_datetime', 'created_datetime'),
    )
    
    def __repr__(self):
        return f"<Template(id={self.id}, template_id={self.template_id}, template_name={self.template_name})>"
    
    def get_config_value(self, key: str, default=None):
        """
        Get a specific configuration value from additional_config.
        
        Args:
            key: Configuration key to retrieve
            default: Default value if key not found
            
        Returns:
            Value from additional_config or default
        """
        if not self.additional_config:
            return default
        return self.additional_config.get(key, default)
    
    def set_config_value(self, key: str, value):
        """
        Set a specific configuration value in additional_config.
        
        Args:
            key: Configuration key to set
            value: Value to set
        """
        if not self.additional_config:
            self.additional_config = {}
        self.additional_config[key] = value

