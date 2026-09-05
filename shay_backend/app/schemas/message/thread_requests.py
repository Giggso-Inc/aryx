"""
Thread create/update/move/phone-lookup request+response schemas.

Split out of the former app/schemas/message.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID


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


class PhoneThreadRequest(BaseModel):
    """Phone number based thread lookup/creation request"""
    phone_number: str = Field(..., min_length=6, max_length=18, pattern=r"^\+?\d{6,17}$")
    channel_id: str = Field(..., description="Channel ID where the thread should be created or found")


class PhoneThreadResponse(BaseModel):
    """Response indicating thread associated with phone number"""
    thread_id: str
    phone_number: str
    is_new: bool


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
