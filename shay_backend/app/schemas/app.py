"""
Pydantic schemas for App management
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator
import uuid


class AppBase(BaseModel):
    """Base schema for App"""
    app_name: str = Field(..., min_length=1, max_length=255, description="Name of the application")
    app_key: str = Field(..., min_length=1, max_length=100, description="Internal unique identifier for the app")
    app_description: Optional[str] = Field(None, description="Description of the application")
    app_image: Optional[str] = Field(None, max_length=500, description="URL to app image")
    is_active: bool = Field(True, description="Whether the app is active")
    is_public: bool = Field(True, description="Whether the app is publicly available")
    version: Optional[str] = Field(None, max_length=50, description="App version")
    category: Optional[str] = Field(None, max_length=100, description="App category")
    tags: Optional[str] = Field(None, description="JSON string for tags")


class AppCreate(AppBase):
    """Schema for creating a new app"""
    
    @validator('app_name')
    def validate_app_name(cls, v):
        if not v.strip():
            raise ValueError('App name cannot be empty')
        return v.strip()
    
    @validator('app_key')
    def validate_app_key(cls, v):
        if not v.strip():
            raise ValueError('App key cannot be empty')
        # Ensure app_key contains only alphanumeric characters and underscores
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('App key can only contain alphanumeric characters and underscores')
        return v.strip()


class AppUpdate(BaseModel):
    """Schema for updating an app"""
    app_name: Optional[str] = Field(None, min_length=1, max_length=255)
    app_key: Optional[str] = Field(None, min_length=1, max_length=100)
    app_description: Optional[str] = None
    app_image: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None
    version: Optional[str] = Field(None, max_length=50)
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[str] = None


class AppResponse(AppBase):
    """Schema for app response"""
    id: str
    sub_category: Optional[str] = Field(None, description="Computed subcategory: 'Cloud Drive' or 'Datasource' (derived from app_key)")
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AppList(BaseModel):
    """Schema for list of apps"""
    apps: List[AppResponse]
    total: int
    page: int
    size: int
    pages: int


class AppStats(BaseModel):
    """Schema for app statistics"""
    total_apps: int
    active_apps: int
    public_apps: int
    categories: List[str]
    recent_apps: List[AppResponse]


class AppCategoryListResponse(BaseModel):
    """Schema for category list response"""
    categories: List[str] = Field(..., description="List of available app categories")
    total: int = Field(..., description="Total number of categories") 