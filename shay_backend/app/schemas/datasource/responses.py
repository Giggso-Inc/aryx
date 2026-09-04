"""
Datasource response schemas (single, list, bulk-create, with-relations).

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class DatasourceResponse(BaseModel):
    """Datasource response schema"""
    id: str
    name: str
    filename: str
    storage_type: str
    provider: Optional[str] = None
    app_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    giggso_vault_id: Optional[str] = None  # Reference to gg_vault table (UUID)
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = None
    channel_id: str
    workspace_id: str
    company_id: str
    added_by: str
    is_active: bool
    is_connected: bool
    is_processed: bool
    processing_status: str
    error_message: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    processing_time: Optional[int] = None
    record_count: int
    is_embedding_required: bool
    embedding_status: int
    created_at: datetime
    updated_at: datetime
    aryx_ingestion_status: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Present only when this datasource's datasource_metadata carries an "
            "aryx.discovery_id (linked via a kind='aryx' upload) — live Aryx job "
            "status merged in at read time: {status, stage, pct, detail, ...} "
            "(same shape as Aryx's GET /admin/jobs/{id}). None for every datasource "
            "without that linkage — additive, backward compatible."
        ),
    )

    class Config:
        from_attributes = True


class DatasourceList(BaseModel):
    """Datasource list response schema"""
    datasources: List[DatasourceResponse]
    total: int
    page: int
    size: int


class DatasourceBulkResponse(BaseModel):
    """Bulk datasource creation response"""
    created_datasources: List[DatasourceResponse]
    failed_datasources: List[Dict[str, Any]]
    total_created: int
    total_failed: int


class DatasourceWithRelationsResponse(BaseModel):
    """Datasource response schema with full user and channel objects"""
    id: str
    name: str
    filename: str
    storage_type: str
    provider: Optional[str] = None
    app_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    giggso_vault_id: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = None
    channel: Dict[str, Any]  # Full channel object as dict
    added_by_user: Dict[str, Any]  # Full user object as dict
    is_active: bool
    is_connected: bool
    is_processed: bool
    processing_status: str
    error_message: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    processing_time: Optional[int] = None
    record_count: int
    is_embedding_required: bool
    embedding_status: int
    created_at: datetime
    updated_at: datetime


class DatasourceListWithRelations(BaseModel):
    """Datasource list response schema with full user and channel objects"""
    datasources: List[DatasourceWithRelationsResponse]
    total: int
    page: int
    size: int
    pages: int
