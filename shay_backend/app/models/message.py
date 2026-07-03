"""
Message model for thread-based messaging with AI integration
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Index, ForeignKey
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB, DialectUUIDArray
from sqlalchemy.orm import relationship
from app.core.database import Base


class Message(Base):
    """Message model for thread-based messaging with AI integration"""
    
    __tablename__ = "gg_messages"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Message content
    content = Column(Text, nullable=False)
    message_type = Column(String(50), default="user", nullable=False)  # user, ai, system
    
    # Response text (from DDL schema)
    response_text = Column(Text, nullable=True)  # Added from DDL
    
    # Thread association — scope is derived via the thread
    thread_id = Column(UUID(as_uuid=True), ForeignKey("gg_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # User association
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Null for AI messages
    
    # Query-Response mapping
    query_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Links system responses to user queries
    
    # Message metadata
    is_ai_processed = Column(Boolean, default=False, nullable=False)
    ai_provider = Column(String(50), nullable=True)
    ai_model = Column(String(100), nullable=True)
    ai_processing_time = Column(Integer, nullable=True)  # Processing time in milliseconds
    
    # Message status
    is_visible = Column(Boolean, default=True, nullable=False)
    is_pinned = Column(Boolean, default=False, nullable=False)
    
    # Message ordering
    sequence_number = Column(Integer, nullable=False, default=0)
    
    # Additional metadata
    message_metadata = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # Citations for system messages (ML responses)
    citations = Column(JSONB, nullable=True)  # Array of citation objects with name and type

    # Usage metrics for system messages (token_usage, time_usage, confidence_score, app_usage, etc.)
    usage_metrics = Column(JSONB, nullable=True)  # Store usage metrics as JSONB dict for AI token usage tracking

    # Attachment IDs array (PostgreSQL ARRAY(UUID), Oracle JSON)
    attachment_ids = Column(DialectUUIDArray(), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Dialect-agnostic indexes
    __table_args__ = (
        Index('idx_message_thread_time', 'thread_id', 'created_at'),
        Index('idx_message_user_time', 'user_id', 'created_at'),
        Index('idx_message_ai_processed', 'is_ai_processed', 'created_at'),
        Index('idx_message_type_time', 'message_type', 'created_at'),
        Index('idx_message_sequence', 'thread_id', 'sequence_number'),
    )
    
    # Relationships
    approvals = relationship("Approval", back_populates="message")
    
    def __repr__(self):
        return f"<Message(id={self.id}, thread_id={self.thread_id}, type={self.message_type})>"
    
    @property
    def is_user_message(self) -> bool:
        """Check if message is from user"""
        return self.message_type == "user"
    
    @property
    def is_ai_message(self) -> bool:
        """Check if message is from AI"""
        return self.message_type == "ai"
    
    @property
    def is_system_message(self) -> bool:
        """Check if message is system message"""
        return self.message_type == "system"
    
    def get_processing_time_seconds(self) -> float:
        """Get AI processing time in seconds"""
        if self.ai_processing_time:
            return self.ai_processing_time / 1000.0
        return 0.0


class Thread(Base):
    """Thread model for organizing messages"""
    
    __tablename__ = "gg_threads"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Thread information
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    
    # Channel association — workspace is derived via the channel
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Thread settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    
    # Thread metadata
    message_count = Column(Integer, default=0, nullable=False)
    last_message_at = Column(DateTime, nullable=True)
    
    # AI integration
    ai_enabled = Column(Boolean, default=True, nullable=False)
    ai_summary = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_thread_channel_time', 'channel_id', 'created_at'),
        Index('idx_thread_active_archived', 'is_active', 'is_archived'),
        Index('idx_thread_last_message', 'last_message_at'),
    )

    def __repr__(self):
        return f"<Thread(id={self.id}, title={self.title}, channel_id={self.channel_id})>"
    
    def get_title_or_default(self) -> str:
        """Get thread title or default title"""
        return self.title or f"Thread {str(self.id)[:8]}" 