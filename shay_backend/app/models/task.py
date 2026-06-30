"""
Task model for task management system

This module defines the Task SQLAlchemy model for tracking manual or AI-generated tasks
with comprehensive status tracking, priority management, and checklist integration.

File: app/models/task.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Task creation and management with multiple statuses
- Priority levels from Low to Blocker
- Integration with workspaces, channels, threads, and messages
- Checklist support for task breakdown
- Comprehensive metadata and tagging system
- Audit trail with timestamps and user tracking
"""

from datetime import datetime, date, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Date, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB

from app.core.database import Base
from sqlalchemy.orm import relationship


class Task(Base):
    """Task model for tracking manual or AI-generated tasks"""
    
    __tablename__ = "gg_tasks"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Task information
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Assignment
    assigned_to = Column(UUID(as_uuid=True), nullable=True, index=True)  # User ID
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)  # User ID who created the task
    
    # Task status and metadata
    status = Column(String(50), default="Open", nullable=False)  # Open, In Progress, On Hold, Close
    source = Column(String(50), nullable=True)  # ai_generated, manual, system
    due_date = Column(DateTime, nullable=True)  # Changed from Date to DateTime to support time
    
    # Task context — linked only via message_id
    message_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    # Task metadata
    priority = Column(String(20), default="Medium", nullable=False)  # Low, Medium, High, Critical, Blocker
    tags = Column(JSONB, nullable=True)  # JSON array of tags
    task_metadata = Column(JSONB, nullable=True)  # Additional task data (renamed from metadata)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    checklists = relationship("Checklist", back_populates="task", cascade="all, delete-orphan", order_by="Checklist.order_index")
    
    # Note: Relationships are handled manually in routes to avoid foreign key constraint issues
    # User and context data is loaded separately when needed
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_task_title_hash', 'title'),
        Index('idx_task_status_time', 'status', 'created_at'),
        Index('idx_task_assigned_to', 'assigned_to', 'status'),
        Index('idx_task_source_time', 'source', 'created_at'),
        Index('idx_task_due_date', 'due_date'),
        Index('idx_task_priority_status', 'priority', 'status'),
    )
    
    def __repr__(self):
        return f"<Task(id={self.id}, title={self.title}, status={self.status})>"
    
    @property
    def is_completed(self) -> bool:
        """Check if task is completed"""
        return self.status == "Close"
    
    @property
    def is_overdue(self) -> bool:
        """Check if task is overdue"""
        if not self.due_date:
            return False
        from datetime import datetime, timezone
        return self.due_date < datetime.now(timezone.utc) and self.status not in ["Close"]
    
    @property
    def is_urgent(self) -> bool:
        """Check if task is urgent priority (Critical or Blocker)"""
        return self.priority in ["Critical", "Blocker"]
    
    def mark_completed(self):
        """Mark task as completed (Close status)"""
        self.status = "Close"
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
    
    def assign_to(self, user_id: str):
        """Assign task to user"""
        self.assigned_to = user_id
        self.updated_at = datetime.now(timezone.utc)
    
    def update_status(self, status: str):
        """Update task status with completion tracking"""
        self.status = status
        if status == "Close":
            self.completed_at = datetime.now(timezone.utc)
        elif status != "Close":
            self.completed_at = None
        self.updated_at = datetime.now(timezone.utc)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "assigned_to": str(self.assigned_to) if self.assigned_to else None,
            "status": self.status,
            "source": self.source,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "tags": self.tags,
            "task_metadata": self.task_metadata,  # Updated to use new column name
            "message_id": str(self.message_id) if self.message_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        } 