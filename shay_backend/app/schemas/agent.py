"""
AI Agent schemas for request/response validation
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AICallback(BaseModel):
    """AI callback request schema"""
    message_id: str
    thread_id: str
    workspace_id: str
    ai_provider: str
    ai_model: str
    response_content: str
    response_type: str = "analysis"
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    processing_time_ms: Optional[int] = None
    status: str = "completed"
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class AIStatus(BaseModel):
    """AI status update request schema"""
    message_id: str
    status: str  # pending, processing, completed, failed
    progress: Optional[float] = Field(None, ge=0.0, le=1.0)
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AIHealth(BaseModel):
    """AI health response schema"""
    status: str
    provider: str
    model: str
    response_time_ms: Optional[int] = None
    last_check: datetime
    error_count: int = 0
    success_rate: float = 0.0


class AIStats(BaseModel):
    """AI statistics response schema"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_response_time_ms: float
    total_processing_time_ms: int
    requests_today: int
    requests_this_week: int
    requests_this_month: int
    top_providers: List[Dict[str, Any]]
    top_models: List[Dict[str, Any]]


class AITrigger(BaseModel):
    """AI trigger request schema"""
    message_id: str
    force_retry: bool = False
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None


class AIWebhookPayload(BaseModel):
    """AI webhook payload schema"""
    message_id: str
    thread_id: str
    workspace_id: str
    user_id: str
    content: str
    callback_url: str
    callback_token: str
    ai_provider: str
    ai_model: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime 