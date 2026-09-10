"""
Datasource processing request/response schemas plus the per-storage-type
create schemas (local/cloud/app) that were declared alongside them in the
original monolithic file.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, List

from pydantic import BaseModel, Field


class DatasourceProcessingRequest(BaseModel):
    """Request to process datasources"""
    datasource_ids: List[str] = Field(..., min_items=1, max_items=50)


class DatasourceProcessingResponse(BaseModel):
    """Response for datasource processing"""
    message: str
    processed_count: int
    failed_count: int
    processing_jobs: List[str]


# Storage type specific schemas
class LocalDatasourceCreate(BaseModel):
    """Local storage datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    file_path: str
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")


class CloudDatasourceCreate(BaseModel):
    """Cloud storage datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    provider: str = Field(..., pattern="^(local|s3|azure|gcp|oracle)$")
    bucket_name: str
    region: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")


class AppDatasourceCreate(BaseModel):
    """App-based datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    app_type: str = Field(..., pattern="^(googleDrive|sharePoint|dropbox|oneDrive)$")
    app_id: str
    folder_id: Optional[str] = None
    file_id: Optional[str] = None
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
