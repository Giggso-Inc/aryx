"""
Internal-API datasource create request schemas (thread-scoped).

Split out of the former app/schemas/datasource/core.py during Phase 5b
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator

from .config import DatasourceConfig


class DatasourceCreateInternal(BaseModel):
    """Single datasource creation request for internal API (thread-level)"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    filename: Optional[str] = Field(None, max_length=500)
    storage_type: str = Field(..., pattern="^(local|cloud|app|database)$")
    provider: Optional[str] = None  # s3, azure, etc.
    app_provider: Optional[str] = None  # pipedream, etc. for app storage
    app_type: Optional[str] = None  # googleDrive, sharePoint, etc.
    config: Optional[DatasourceConfig] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    thread_id: str  # Thread ID instead of channel_id
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    location: Optional[str] = Field(None, description="Cloud storage location URL (for cloud storage type)")
    accessToken: Optional[str] = Field(None, description="Access token for cloud storage (for cloud storage type)")
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    is_embedding_required: Optional[bool] = Field(False, description="Whether embedding is required for this datasource")

    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v, info) -> Optional[str]:
        """Validate filename based on storage type"""
        storage_type = info.data.get('storage_type')

        # For local storage, filename is required
        if storage_type == 'local' and not v:
            raise ValueError('filename is required for local storage')

        # For cloud storage, filename is optional (can be extracted from URL)
        if storage_type == 'cloud' and not v:
            # Check if we have file_url to extract filename
            file_url = info.data.get('file_url')
            if not file_url:
                raise ValueError('Either filename or file_url is required for cloud storage')

        # For app storage, filename is optional (will be handled in code)
        # No validation needed - empty/null filenames are handled in the bulk API

        return v


class DatasourceBulkCreateInternal(BaseModel):
    """Bulk datasource creation request for internal API (thread-level)"""
    datasources: List[DatasourceCreateInternal] = Field(..., min_items=1, max_items=100)
