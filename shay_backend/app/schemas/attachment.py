"""
Attachment schemas for request/response validation
"""

from datetime import datetime
from typing import Optional, List, Dict, Union
from uuid import UUID
from pydantic import BaseModel, Field


class AttachmentCreate(BaseModel):
    """Attachment creation request schema"""
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    file_extension: str
    message_id: Optional[Union[str, UUID]] = None
    is_public: bool = False


class AttachmentUpdate(BaseModel):
    """Attachment update request schema"""
    is_public: Optional[bool] = None
    processing_status: Optional[str] = None
    content_summary: Optional[str] = None


class AttachmentResponse(BaseModel):
    """Attachment response schema"""
    id: Union[str, UUID]
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    file_extension: str
    message_id: Optional[Union[str, UUID]] = None
    workspace_id: Union[str, UUID]
    user_id: Union[str, UUID]
    is_processed: bool
    processing_status: str
    processing_error: Optional[str] = None
    is_public: bool
    content_summary: Optional[str] = None
    log_entries_count: int
    error_count: int
    warning_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AttachmentList(BaseModel):
    """Attachment list response schema"""
    attachments: List[AttachmentResponse]
    total: int
    page: int
    size: int


class AttachmentStats(BaseModel):
    """Attachment statistics schema"""
    total_attachments: int
    total_size_bytes: int
    processed_count: int
    failed_count: int
    pending_count: int
    log_files_count: int
    json_files_count: int
    xml_files_count: int


class TaskAttachmentCreate(BaseModel):
    """Task attachment creation request schema"""
    task_id: Union[str, UUID]
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    file_extension: str
    is_public: bool = False


class TaskAttachmentResponse(BaseModel):
    """Task attachment response schema"""
    id: Union[str, UUID]
    task_id: Union[str, UUID]
    filename: str
    original_filename: str
    file_size: int
    mime_type: str
    file_extension: str
    workspace_id: Union[str, UUID]
    user_id: Union[str, UUID]
    is_processed: bool
    processing_status: str
    processing_error: Optional[str] = None
    is_public: bool
    content_summary: Optional[str] = None
    log_entries_count: int
    error_count: int
    warning_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class TaskAttachmentList(BaseModel):
    """Task attachment list response schema"""
    attachments: List[TaskAttachmentResponse]
    total: int
    page: int
    size: int


class TaskAttachmentStats(BaseModel):
    """Task attachment statistics schema"""
    total_attachments: int
    total_size_bytes: int
    processed_count: int
    failed_count: int
    pending_count: int
    by_file_type: Dict[str, int]  # Count by file extension 