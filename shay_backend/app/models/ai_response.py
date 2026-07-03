"""
AI Response model for storing AI analysis results and metadata
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, Float, Index
from sqlalchemy.sql import func
from app.core.db_types import UUID, JSONB

from app.core.database import Base


class AIResponse(Base):
    """AI Response model for storing AI analysis results and metadata"""
    
    __tablename__ = "gg_ai_responses"
    
    # Primary key - Using native UUID for PostgreSQL
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Message association
    message_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    thread_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # AI processing information
    ai_provider = Column(String(50), nullable=False)  # openai, anthropic, custom
    ai_model = Column(String(100), nullable=False)  # gpt-4, claude-3, etc.
    processing_time_ms = Column(Integer, nullable=True)
    
    # Response content
    response_content = Column(Text, nullable=False)
    response_type = Column(String(50), default="analysis", nullable=False)  # analysis, summary, error, warning
    
    # Quality metrics
    confidence_score = Column(Float, nullable=True)  # 0.0 to 1.0
    relevance_score = Column(Float, nullable=True)  # 0.0 to 1.0
    
    # Processing status
    status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Metadata
    response_metadata = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    tags = Column(JSONB, nullable=True)  # Changed to JSONB for PostgreSQL
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    processed_at = Column(DateTime, nullable=True)
    
    # PostgreSQL-specific indexes
    __table_args__ = (
        Index('idx_ai_response_message_time', 'message_id', 'created_at'),
        Index('idx_ai_response_thread_time', 'thread_id', 'created_at'),
        Index('idx_ai_response_workspace_time', 'workspace_id', 'created_at'),
        Index('idx_ai_response_provider_model', 'ai_provider', 'ai_model'),
        Index('idx_ai_response_status_time', 'status', 'created_at'),
        Index('idx_ai_response_type_time', 'response_type', 'created_at'),
        Index('idx_ai_response_confidence', 'confidence_score'),
        Index('idx_ai_response_relevance', 'relevance_score'),
    )
    
    def __repr__(self):
        return f"<AIResponse(id={self.id}, message_id={self.message_id}, provider={self.ai_provider})>"
    
    @property
    def is_completed(self) -> bool:
        """Check if AI processing is completed"""
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        """Check if AI processing failed"""
        return self.status == "failed"
    
    @property
    def is_pending(self) -> bool:
        """Check if AI processing is pending"""
        return self.status == "pending"
    
    @property
    def is_processing(self) -> bool:
        """Check if AI processing is in progress"""
        return self.status == "processing"
    
    @property
    def processing_time_seconds(self) -> float:
        """Get processing time in seconds"""
        if self.processing_time_ms:
            return self.processing_time_ms / 1000.0
        return 0.0
    
    @property
    def has_high_confidence(self) -> bool:
        """Check if response has high confidence"""
        return self.confidence_score and self.confidence_score >= 0.8
    
    @property
    def has_high_relevance(self) -> bool:
        """Check if response has high relevance"""
        return self.relevance_score and self.relevance_score >= 0.8
    
    def get_quality_score(self) -> float:
        """Calculate overall quality score"""
        if not self.confidence_score or not self.relevance_score:
            return 0.0
        return (self.confidence_score + self.relevance_score) / 2.0
    
    def can_be_retried(self) -> bool:
        """Check if AI processing can be retried"""
        return self.status == "failed" and self.retry_count < 3 