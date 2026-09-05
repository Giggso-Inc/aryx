"""
Shared small schemas reused across message/thread request and response
schemas (user bean, attachment references, citations).

Split out of the former app/schemas/message.py to keep each file under the
Raven 150-line style limit.
"""

from datetime import datetime
from typing import Optional, Union
from pydantic import BaseModel, Field, field_serializer
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


class Citation(BaseModel):
    """Citation schema for document references in ML responses"""
    name: str = Field(..., description="Document/file name")
    type: str = Field(..., description="File type/extension (e.g., 'xlsx', 'pdf')")

    class Config:
        from_attributes = True
