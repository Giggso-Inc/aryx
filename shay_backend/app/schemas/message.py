"""
Message schemas for request/response validation
"""

from datetime import datetime
from typing import Optional, List, Union, Dict, Any
from pydantic import BaseModel, Field, field_serializer, ConfigDict
from uuid import UUID


class UserBean(BaseModel):
    """User bean schema for message responses"""
    id: Union[str, UUID]
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = Field(None, description="User avatar URL from DB")

    @field_serializer('id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value) if value else None
    
    class Config:
        from_attributes = True


class AttachmentReference(BaseModel):
    """Attachment reference schema for message attachments"""
    id: Union[str, UUID] = Field(..., description="Attachment ID")
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type of the file")
    file_extension: str = Field(..., description="File extension")
    is_public: bool = Field(False, description="Whether the attachment is public")
    
    @field_serializer('id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value) if value else None
    
    class Config:
        from_attributes = True


class AttachmentDetails(BaseModel):
    """Detailed attachment schema for message responses"""
    id: Union[str, UUID]
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    file_extension: str
    storage_url: Optional[str] = None
    is_public: bool
    is_processed: bool
    processing_status: str
    content_summary: Optional[str] = None
    created_at: datetime
    
    @field_serializer('id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value) if value else None
    
    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    """Message creation request schema"""
    content: str = Field(..., min_length=1)
    thread_id: str
    message_type: str = "user"  # user, ai, system
    query_id: Optional[str] = Field(None, description="ID of the query message for system responses")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with this message")


class MessageUpdate(BaseModel):
    """Message update request schema"""
    message_id: str = Field(..., description="ID of the message to update")
    thread_id: str = Field(..., description="Thread ID of the message")
    content: str = Field(..., min_length=1, description="Updated message content")
    message_type: str = Field("user", description="Message type: user, ai, system")
    attachment_ids: Optional[List[str]] = Field(None, description="List of attachment IDs to associate with this message (empty list to remove all attachments)")
    is_visible: Optional[bool] = None
    is_pinned: Optional[bool] = None


class MessageDelete(BaseModel):
    """Message deletion request schema"""
    message_id: str = Field(..., description="ID of the message to delete")
    thread_id: str = Field(..., description="Thread ID of the message")


class HideThreadMessagesBody(BaseModel):
    """Request body for hiding a message in a thread (soft-hide: is_visible=false)."""
    message_id: str = Field(..., description="Message UUID to hide in the thread")


class HideThreadMessagesResponse(BaseModel):
    """Response after hiding a message in a thread."""
    success: bool = Field(..., description="Whether the hide operation succeeded")
    message: str = Field(..., description="Human-readable status message")
    hidden_count: int = Field(..., description="Number of messages that were set to hidden (0 or 1)")
    message_id: str = Field(..., description="Message ID that was hidden")


class Citation(BaseModel):
    """Citation schema for document references in ML responses"""
    name: str = Field(..., description="Document/file name")
    type: str = Field(..., description="File type/extension (e.g., 'xlsx', 'pdf')")
    
    class Config:
        from_attributes = True


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


class ThreadCreate(BaseModel):
    """Thread creation request schema"""
    channel_id: str
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, description="Optional description for the thread")


class ThreadUpdate(BaseModel):
    """Thread update request schema"""
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, description="Optional description for the thread")
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    ai_summary: Optional[str] = None


class ThreadResponse(BaseModel):
    """Thread response schema"""
    id: Union[str, UUID]
    title: Optional[str] = None
    description: Optional[str] = None
    channel_id: Union[str, UUID]
    is_active: bool
    is_archived: bool
    message_count: int
    last_message_at: Optional[datetime] = None
    ai_enabled: bool
    ai_summary: Optional[str] = None
    first_message_id: Optional[Union[str, UUID]] = None  # ID of the first message in the thread
    created_at: datetime
    updated_at: datetime
    
    @field_serializer('id', 'channel_id', 'first_message_id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value) if value else None
    
    class Config:
        from_attributes = True


class ThreadList(BaseModel):
    """Thread list response schema"""
    threads: List[ThreadResponse]
    total: int
    page: int
    size: int


class PhoneThreadRequest(BaseModel):
    """Phone number based thread lookup/creation request"""
    phone_number: str = Field(..., min_length=6, max_length=18, pattern=r"^\+?\d{6,17}$")
    channel_id: str = Field(..., description="Channel ID where the thread should be created or found")


class PhoneThreadResponse(BaseModel):
    """Response indicating thread associated with phone number"""
    thread_id: str
    phone_number: str
    is_new: bool


class MessageList(BaseModel):
    """Message list response schema"""
    messages: List[MessageResponse]
    total: int
    page: int
    size: int


class ThreadSummary(BaseModel):
    """Thread summary response schema"""
    thread_id: Union[str, UUID]
    title: Optional[str] = None
    message_count: int
    last_message_at: Optional[datetime] = None
    ai_summary: Optional[str] = None
    created_at: datetime
    
    @field_serializer('thread_id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)


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


class ThreadMoveRequest(BaseModel):
    """Request schema for moving a thread to another regular channel."""
    thread_id: UUID = Field(..., description="Thread UUID to move")
    new_channel_id: UUID = Field(..., description="Destination channel UUID")

    model_config = ConfigDict(from_attributes=True)


class ThreadMoveResponse(BaseModel):
    """Response schema for thread move operation with per-table update counts."""
    thread_id: UUID = Field(..., description="Thread that was moved")
    old_channel_id: UUID = Field(..., description="Source channel UUID")
    new_channel_id: UUID = Field(..., description="Destination channel UUID")
    updated_counts: Dict[str, int] = Field(
        ...,
        description="Row counts updated per table (e.g. gg_messages, gg_approvals, gg_tasks, gg_attachments, gg_email_attachments, gg_shortened_urls)",
    )

    model_config = ConfigDict(from_attributes=True) 