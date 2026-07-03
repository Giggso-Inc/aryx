"""
Checklist model for task checklists

This module defines the Checklist SQLAlchemy model for managing task checklists
with ordering, completion tracking, and metadata support.

File: app/models/checklist.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Ordered checklist items with automatic sequencing
- Completion tracking with user attribution and timestamps
- Metadata support for additional information
- Cascade deletion with parent tasks
- Comprehensive audit trail
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class Checklist(Base):
    """Checklist model for task checklists"""
    
    __tablename__ = "gg_checklists"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Task association
    task_id = Column(UUID(as_uuid=True), ForeignKey("gg_tasks.id"), nullable=False, index=True)
    
    # Checklist content
    text = Column(String(500), nullable=False)
    
    # Ordering and status
    order_index = Column(Integer, nullable=False, index=True)  # For maintaining order
    is_completed = Column(Boolean, default=False, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(UUID(as_uuid=True), nullable=True, index=True)  # User who completed it
    
    # Additional metadata
    checklist_metadata = Column(JSONB, nullable=True)  # For any additional data
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    task = relationship("Task", back_populates="checklists")
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_checklist_task_order', 'task_id', 'order_index'),
        Index('idx_checklist_task_status', 'task_id', 'is_completed'),
        Index('idx_checklist_completed_by', 'completed_by'),
        Index('idx_checklist_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Checklist(id={self.id}, text={self.text[:30]}..., order={self.order_index}, completed={self.is_completed})>"
    
    def mark_completed(self, user_id: str = None):
        """Mark checklist item as completed"""
        self.is_completed = True
        self.completed_at = datetime.now()
        self.completed_by = user_id
        self.updated_at = datetime.now()
    
    def mark_incomplete(self):
        """Mark checklist item as incomplete"""
        self.is_completed = False
        self.completed_at = None
        self.completed_by = None
        self.updated_at = datetime.now()
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": str(self.id),
            "task_id": str(self.task_id),
            "text": self.text,
            "order_index": self.order_index,
            "is_completed": self.is_completed,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "checklist_metadata": self.checklist_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
