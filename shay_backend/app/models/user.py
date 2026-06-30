"""
User model for authentication and authorization.

This module defines the SQLAlchemy ORM model for users, including all user-related
fields, relationships, and business logic methods. It handles user authentication,
role-based access control, and company associations for multi-tenant architecture.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

# Standard library imports for date/time operations
from datetime import datetime

# SQLAlchemy core components for table definition and column types
from sqlalchemy import Column, String, DateTime, Boolean, Text, Index, ForeignKey

# SQLAlchemy ORM components for relationships
from sqlalchemy.orm import relationship

# SQLAlchemy SQL functions for default values and timestamps
from sqlalchemy.sql import func

# Dialect-aware types (PostgreSQL/Oracle)
from app.core.db_types import UUID, JSONB
from app.core.database import Base


class User(Base):
    """User model for authentication and authorization"""
    
    __tablename__ = "gg_users"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # User information
    name = Column(String(255), nullable=True)
    email_id = Column(String(255), unique=True, nullable=True, index=True)
    avatar_url = Column(String(500), nullable=True)
    
    # Company association (multi-tenant)
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=True, index=True)
    
    # Role and permissions
    role = Column(String(50), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    
    # OAuth fields
    google_id = Column(String(255), unique=True, nullable=True)
    oauth_provider = Column(String(50), nullable=False, default="local")
    
    # User preferences
    preferences = Column(JSONB, nullable=True)
    
    # Timestamps
    last_login = Column(DateTime, nullable=True)
    created_datetime = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_datetime = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Password (hashed)
    password_hash = Column(Text, nullable=True)
    
    # Dialect-agnostic indexes
    __table_args__ = (
        Index('idx_user_hash', 'id'),
        Index('idx_user_email', 'email_id'),
    )
    
    # Relationships
    company = relationship("Company", back_populates="users")
    requested_approvals = relationship("Approval", foreign_keys="Approval.requested_by_user_id", back_populates="requested_by_user")
    assigned_approvals = relationship("Approval", foreign_keys="Approval.approver_user_id", back_populates="approver_user")
    
    def __repr__(self):
        return f"<User(id={self.id}, email_id={self.email_id}, role={self.role})>"
    
    @property
    def is_admin(self) -> bool:
        """
        Check if user has admin role.
        
        Returns:
            bool: True if user role is 'admin', False otherwise
        """
        return self.role == "admin"
    
    @property
    def is_guest(self) -> bool:
        """
        Check if user has guest role.
        
        Returns:
            bool: True if user role is 'guest', False otherwise
        """
        return self.role == "guest"
    
    def can_access_company(self, company_id: str) -> bool:
        """
        Check if user can access company data.
        
        Args:
            company_id: UUID string of the company to check access for
            
        Returns:
            bool: True if user is admin or belongs to the specified company
        """
        if self.is_admin:
            return True
        return str(self.company_id) == company_id
    
    def can_manage_workspace(self, workspace_company_id: str) -> bool:
        """
        Check if user can manage (create/edit/delete) workspace.
        
        Args:
            workspace_company_id: UUID string of the workspace's company
            
        Returns:
            bool: True if user is admin or belongs to the company with admin/user role
        """
        if self.is_admin:
            return True
        return str(self.company_id) == workspace_company_id and self.role in ["admin", "user"]
    
    def can_view_workspace(self, workspace_company_id: str) -> bool:
        """
        Check if user can view workspace content.
        
        Args:
            workspace_company_id: UUID string of the workspace's company
            
        Returns:
            bool: True if user is admin or belongs to the specified company
        """
        if self.is_admin:
            return True
        return str(self.company_id) == workspace_company_id 