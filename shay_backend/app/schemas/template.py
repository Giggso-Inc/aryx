"""
Template schemas for file-based template API validation.

This module defines Pydantic schemas for Template file API endpoints, including
file response validation, database record management, and data transformation.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0
"""

# Standard library imports
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

# Pydantic imports for data validation and serialization
from pydantic import BaseModel, Field, ConfigDict, validator


class TemplateFileResponse(BaseModel):
    """Schema for individual template file response"""
    
    model_config = ConfigDict(from_attributes=True)
    
    file_name: str = Field(..., description="Name of the template file")
    file_path: str = Field(..., description="Full path to the template file")
    content: str = Field(..., description="Content of the template file")
    file_size: int = Field(..., description="Size of the file in bytes")
    last_modified: datetime = Field(..., description="Last modification timestamp")


class TemplateFileListResponse(BaseModel):
    """Schema for template file list response"""
    
    files: List[TemplateFileResponse] = Field(..., description="List of template files")
    directory: str = Field(..., description="Template directory path")
    total_files: int = Field(..., description="Total number of template files")


# Database template schemas
class TemplateBase(BaseModel):
    """Base schema for Template with common fields"""
    
    template_id: str = Field(..., description="Unique template identifier (auto-generated format based on type)")
    template_name: str = Field(..., description="Template name (file name)")
    file_path: Optional[str] = Field(None, description="File path for storage")
    file_size: Optional[str] = Field(None, description="File size")
    additional_config: Optional[Dict[str, Any]] = Field(default={}, description="Additional configuration as JSON")


class TemplateCreate(TemplateBase):
    """Schema for creating a new template"""
    pass


class TemplateUpdate(BaseModel):
    """Schema for updating a template"""
    
    template_name: Optional[str] = Field(None, description="Template name (file name)")
    file_path: Optional[str] = Field(None, description="File path for storage")
    file_size: Optional[str] = Field(None, description="File size")
    additional_config: Optional[Dict[str, Any]] = Field(None, description="Additional configuration as JSON")


class TemplateResponse(TemplateBase):
    """Schema for template response"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(..., description="Unique UUID identifier")
    created_datetime: datetime = Field(..., description="Creation timestamp")
    updated_datetime: datetime = Field(..., description="Last update timestamp")


class TemplateListResponse(BaseModel):
    """Schema for template list response with pagination"""
    
    templates: List[TemplateResponse] = Field(..., description="List of templates")
    total: int = Field(..., description="Total number of templates")
    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Number of items per page")
    pages: int = Field(..., description="Total number of pages")


class TemplateUploadRequest(BaseModel):
    """Schema for file upload request"""
    
    template_type: str = Field(..., description="Template type: PWD (password reset), INVT (invitation), OTH (other)")
    platform: str = Field(default="BASE", description="Platform: BASE (Base Shay), ZAPT (Zap Tag), LOGA (LogAnalyzer)")
    template_name: str = Field(..., description="Template name (file name)")
    additional_config: Optional[Dict[str, Any]] = Field(default={}, description="Additional configuration as JSON")
    overwrite: bool = Field(default=False, description="Whether to overwrite existing file")
    
    @validator('template_type')
    def validate_template_type(cls, v):
        allowed_types = ['PWD', 'INVT', 'OTH']
        if v not in allowed_types:
            raise ValueError(f"Template type must be one of: {', '.join(allowed_types)}")
        return v
    
    @validator('platform')
    def validate_platform(cls, v):
        allowed_platforms = ['BASE', 'ZAPT', 'LOGA']
        if v not in allowed_platforms:
            raise ValueError(f"Platform must be one of: {', '.join(allowed_platforms)}")
        return v