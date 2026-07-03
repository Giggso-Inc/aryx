"""
GiggsoVault model for storing vault references for sensitive datasource configuration
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID
from app.core.database import Base


class GiggsoVault(Base):
    """GiggsoVault model for storing vault references for sensitive datasource configuration"""
    
    __tablename__ = "gg_vault"
    
    # Primary key (Python default for PostgreSQL + Oracle compatibility)
    giggso_vault_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Resource and vault information
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # User ID who created the vault entry
    vault_label = Column(String(50), nullable=True)
    vault_unique_id = Column(String(255), nullable=True, unique=True, index=True)
    
    # Timestamps
    created_datetime = Column(DateTime, default=func.current_timestamp(), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_datetime = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    
    # Company and type information
    company_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    vault_type = Column(String(50), nullable=True, index=True)  # e.g., "datasource_config", "azure_credentials", etc.
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_vault_user_id', 'user_id'),
        Index('idx_vault_company_id', 'company_id'),
        Index('idx_vault_type', 'vault_type'),
        Index('idx_vault_created_datetime', 'created_datetime'),
        Index('idx_vault_unique_id', 'vault_unique_id', unique=True),
    )
    
    def __repr__(self):
        return f"<GiggsoVault(id={self.giggso_vault_id}, vault_unique_id={self.vault_unique_id}, vault_type={self.vault_type})>" 