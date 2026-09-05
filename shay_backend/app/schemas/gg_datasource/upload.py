"""
GGDatasource file upload schemas.

Split out of the former app/schemas/gg_datasource.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Any, Dict, List

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    """Response for a single file upload."""
    filename:     str
    file_size:    int
    file_type:    str
    file_url:     str
    storage_path: str
    provider:     str


class FileUploadBulkResponse(BaseModel):
    """Response for bulk file upload."""
    uploaded_files: List[FileUploadResponse]
    failed_files:   List[Dict[str, Any]]
    total_uploaded: int
    total_failed:   int
