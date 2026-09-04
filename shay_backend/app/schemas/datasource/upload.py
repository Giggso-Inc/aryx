"""
File upload response schemas and create-datasource-from-upload schemas.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class FileUploadResponse(BaseModel):
    """Response for file upload"""
    filename: str
    file_size: int
    file_type: str
    file_url: str
    storage_path: str
    provider: str
    aryx_ingestion: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Present only when the bulk-upload call passed kind='aryx' for this "
            "file — {'discovery_id': ...} on success or {'error': ...} on failure. "
            "None for every existing (non-Aryx) upload — additive, backward compatible."
        ),
    )


class FileUploadBulkResponse(BaseModel):
    """Response for bulk file upload"""
    uploaded_files: List[FileUploadResponse]
    failed_files: List[Dict[str, Any]]
    total_uploaded: int
    total_failed: int


class DatasourceFromUpload(BaseModel):
    """Create datasource from uploaded file"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    channel_id: str
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    datasource_metadata: Optional[Dict[str, Any]] = None


class DatasourceFromUploadBulk(BaseModel):
    """Create multiple datasources from uploaded files"""
    datasources: List[DatasourceFromUpload] = Field(..., min_items=1, max_items=100)
