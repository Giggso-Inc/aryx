"""
GGDatasource schemas — request/response validation for the unified
workspace / channel / thread / message datasource endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ScopeLevel = Literal["workspace", "channel", "thread", "message"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class GGDatasourceCreate(BaseModel):
    # Scope — exactly one must be provided
    level:        ScopeLevel
    workspace_id: Optional[str] = None
    channel_id:   Optional[str] = None
    thread_id:    Optional[str] = None
    message_id:   Optional[str] = None

    # Identity
    name:         str            = Field(..., min_length=1, max_length=255)
    filename:     Optional[str]  = None
    storage_type: str            = Field(..., description="local | cloud | app")
    provider:     Optional[str]  = None
    app_type:     Optional[str]  = None

    # Config / metadata
    config:               Optional[Dict[str, Any]] = None
    datasource_metadata:  Optional[Dict[str, Any]] = None

    # Vault (credentials stored externally)
    vault_unique_id: Optional[str] = None

    # File info
    file_size: Optional[int]  = None
    file_type: Optional[str]  = None
    file_url:  Optional[str]  = None
    log_type:  Optional[str]  = None

    # Embedding
    is_embedding_required: bool = False

    @model_validator(mode="after")
    def check_exclusive_arc(self) -> "GGDatasourceCreate":
        mapping = {
            "workspace": self.workspace_id,
            "channel":   self.channel_id,
            "thread":    self.thread_id,
            "message":   self.message_id,
        }
        set_ids = {k: v for k, v in mapping.items() if v is not None}
        if len(set_ids) != 1:
            raise ValueError("Exactly one of workspace_id, channel_id, thread_id, message_id must be set.")
        if self.level not in set_ids:
            raise ValueError(f"level='{self.level}' but the provided scope FK is '{list(set_ids.keys())[0]}'.")
        return self


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class GGDatasourceUpdate(BaseModel):
    name:                 Optional[str]            = None
    filename:             Optional[str]            = None
    storage_type:         Optional[str]            = None
    provider:             Optional[str]            = None
    app_type:             Optional[str]            = None
    config:               Optional[Dict[str, Any]] = None
    datasource_metadata:  Optional[Dict[str, Any]] = None
    vault_unique_id:      Optional[str]            = None
    file_size:            Optional[int]            = None
    file_type:            Optional[str]            = None
    file_url:             Optional[str]            = None
    log_type:             Optional[str]            = None
    is_active:            Optional[bool]           = None
    is_connected:         Optional[bool]           = None
    is_embedding_required: Optional[bool]          = None


# ---------------------------------------------------------------------------
# Processing status update (called by ML agents)
# ---------------------------------------------------------------------------

class ProcessingStatusUpdate(BaseModel):
    processing_status:  Optional[str] = None   # pending | processing | completed | failed
    is_processed:       Optional[bool] = None
    embedding_status:   Optional[int]  = None  # 0=not required|1=in progress|2=completed|3=failed
    error_message:      Optional[str]  = None
    record_count:       Optional[int]  = None
    processing_time:    Optional[int]  = None  # ms


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class GGDatasourceList(BaseModel):
    items:      List[GGDatasourceResponse]
    total:      int
    page:       int
    page_size:  int


# ---------------------------------------------------------------------------
# Resolved (inheritance-aware)
# ---------------------------------------------------------------------------

class ResolvedDatasourcesResponse(BaseModel):
    """All datasources visible at a given scope, grouped by level."""
    workspace:  List[GGDatasourceResponse] = []
    channel:    List[GGDatasourceResponse] = []
    thread:     List[GGDatasourceResponse] = []
    message:    List[GGDatasourceResponse] = []
    total:      int = 0


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Bulk create
# ---------------------------------------------------------------------------

class GGDatasourceBulkCreate(BaseModel):
    datasources: List[GGDatasourceCreate] = Field(..., min_length=1, max_length=100)


class GGDatasourceBulkResponse(BaseModel):
    created_datasources: List[GGDatasourceResponse]
    failed_datasources:  List[Dict[str, Any]]
    total_created:       int
    total_failed:        int


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class GGDatasourceStats(BaseModel):
    total_datasources:      int
    active_datasources:     int
    processed_datasources:  int
    pending_datasources:    int
    failed_datasources:     int
    total_file_size:        int
    storage_type_breakdown: Dict[str, int]
    provider_breakdown:     Dict[str, int]


class DatasourceTypeCount(BaseModel):
    type:  str   # local | cloud | app | database
    count: int


class DatasourceTypeCountResponse(BaseModel):
    counts:          List[DatasourceTypeCount]
    total_connected: int


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class DatasourceConnectionResponse(BaseModel):
    datasource_id: str
    is_connected:  bool
    message:       str
    updated_at:    Optional[datetime] = None


class DatasourceConnectionRequest(BaseModel):
    datasource_ids: List[str] = Field(..., min_length=1, max_length=100)
    action:         str = Field(..., pattern="^(connect|disconnect)$")


class DatasourceBulkConnectionResponse(BaseModel):
    successful_operations: List[DatasourceConnectionResponse]
    failed_operations:     List[Dict[str, Any]]
    total_successful:      int
    total_failed:          int
    action_performed:      str
    message:               str


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

class DatasourceProcessingRequest(BaseModel):
    datasource_id: str


class DatasourceProcessingResponse(BaseModel):
    datasource_id: str
    status:        str
    message:       str


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

class GGEmbeddingStatusResponse(BaseModel):
    scope_level:         str
    scope_id:            str
    total_datasources:   int
    embedding_required:  int
    in_progress:         int
    completed:           int
    failed:              int
    not_required:        int
    datasources:         List[Dict[str, Any]]


class MLWebhookRequest(BaseModel):
    vaultUniqueIds: List[str]
    status:         str   # success | failed
    message:        Optional[str] = None
    processingTime: Optional[int] = None

    model_config = {"populate_by_name": True}


class MLWebhookResponse(BaseModel):
    message:         str
    processed_count: int
    failed_count:    int


class RegenerateEmbeddingResponse(BaseModel):
    success:            bool
    message:            str
    datasource_id:      str
    embedding_status:   int
    status_description: str
