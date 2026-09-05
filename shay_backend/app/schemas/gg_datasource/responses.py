"""
GGDatasource response/list/stats schemas.

Split out of the former app/schemas/gg_datasource.py to keep each file
under the Raven 150-line style limit.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class GGDatasourceResponse(BaseModel):
    id:           str
    level:        str
    workspace_id: Optional[str] = None
    channel_id:   Optional[str] = None
    thread_id:    Optional[str] = None
    message_id:   Optional[str] = None
    added_by:     Optional[str] = None

    name:                 str
    filename:             Optional[str] = None
    storage_type:         str
    provider:             Optional[str] = None
    app_type:             Optional[str] = None
    config:               Optional[Dict[str, Any]] = None
    datasource_metadata:  Optional[Dict[str, Any]] = None
    vault_unique_id:      Optional[str] = None

    file_size:   Optional[int] = None
    file_type:   Optional[str] = None
    file_url:    Optional[str] = None
    log_type:    Optional[str] = None

    is_active:             bool
    is_connected:          bool
    is_processed:          bool
    processing_status:     str
    error_message:         Optional[str] = None
    is_embedding_required: bool
    embedding_status:      int
    last_processed_at:     Optional[datetime] = None
    processing_time:       Optional[int] = None
    record_count:          int

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GGDatasourceList(BaseModel):
    items:      List[GGDatasourceResponse]
    total:      int
    page:       int
    page_size:  int


class ResolvedDatasourcesResponse(BaseModel):
    """All datasources visible at a given scope, grouped by level."""
    workspace:  List[GGDatasourceResponse] = []
    channel:    List[GGDatasourceResponse] = []
    thread:     List[GGDatasourceResponse] = []
    message:    List[GGDatasourceResponse] = []
    total:      int = 0


class GGDatasourceBulkResponse(BaseModel):
    created_datasources: List[GGDatasourceResponse]
    failed_datasources:  List[Dict[str, Any]]
    total_created:       int
    total_failed:        int


class GGDatasourceStats(BaseModel):
    total_datasources:      int
    active_datasources:     int
    processed_datasources:  int
    pending_datasources:    int
    failed_datasources:     int
    total_file_size:        int
    storage_type_breakdown: Dict[str, int]
    provider_breakdown:     Dict[str, int]

