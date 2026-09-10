"""
Message response and ML-service message schemas.

Split out of the former app/schemas/message.py to keep each file under the
Raven 150-line style limit.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_serializer
from uuid import UUID

from .shared import UserBean, AttachmentDetails, Citation


class MessageResponse(BaseModel):
    """Message response schema"""
    id: Union[str, UUID]
    content: str
    message_type: str
    thread_id: Union[str, UUID]
    channel_id: Union[str, UUID]
    user_id: Optional[Union[str, UUID]] = None
    query_id: Optional[Union[str, UUID]] = None
    userBean: Optional[UserBean] = None
    is_ai_processed: bool
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_processing_time: Optional[int] = None
    is_visible: bool
    is_pinned: bool
    sequence_number: int
    attachment_ids: Optional[List[Union[str, UUID]]] = Field(None, description="List of attachment IDs associated with this message")
    attachments: Optional[List[AttachmentDetails]] = Field(None, description="List of attachments associated with this message")
    citations: Optional[List[Citation]] = Field(None, description="List of citations for system messages")
    usage_metrics: Optional[Dict[str, Any]] = Field(None, description="Usage metrics for system messages (token_usage, time_usage, etc.)")
    created_at: datetime
    updated_at: datetime

    @field_serializer('id', 'thread_id', 'channel_id', 'user_id', 'query_id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value) if value else None

    @field_serializer('attachment_ids')
    def serialize_attachment_ids(self, value: Optional[List[Union[str, UUID]]]) -> Optional[List[str]]:
        if value is None:
            return None
        return [str(v) if v else None for v in value]

    class Config:
        from_attributes = True


class MessageList(BaseModel):
    """Message list response schema"""
    messages: List[MessageResponse]
    total: int
    page: int
    size: int


class MLMessageRequest(BaseModel):
    """ML service request schema for storing query and response"""
    prompt: str = Field(..., min_length=1, description="User's query/prompt")
    response: str = Field(..., min_length=1, description="ML generated response")
    thread_id: str = Field(..., description="Thread ID where messages should be stored")
    citations: Optional[List[Citation]] = Field(default_factory=list, description="List of citations/sources used in the response")
    usage_metrics: Optional[Dict[str, Any]] = Field(None, description="Usage metrics (token_usage, time_usage, confidence_score, app_usage, agent_usage)")


class MLMessageResponse(BaseModel):
    """ML service response schema"""
    status: str = Field(..., description="Status of the operation: 'success' or 'failed'")
    message: str = Field(..., description="Status message")
    data: List[MessageResponse] = Field(default_factory=list, description="List of created messages")
