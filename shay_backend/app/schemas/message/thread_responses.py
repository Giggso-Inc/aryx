"""
Thread response/list/summary schemas.

Split out of the former app/schemas/message.py to keep each file under the
Raven 150-line style limit.
"""

from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, field_serializer
from uuid import UUID


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
