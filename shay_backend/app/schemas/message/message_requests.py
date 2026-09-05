"""
Message create/update/delete/hide request schemas.

Split out of the former app/schemas/message.py to keep each file under the
Raven 150-line style limit.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


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
