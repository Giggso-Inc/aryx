"""
GGDatasource create/update/bulk-create request schemas.

Split out of the former app/schemas/gg_datasource.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

ScopeLevel = Literal["workspace", "channel", "thread", "message"]


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


class ProcessingStatusUpdate(BaseModel):
    processing_status:  Optional[str] = None   # pending | processing | completed | failed
    is_processed:       Optional[bool] = None
    embedding_status:   Optional[int]  = None  # 0=not required|1=in progress|2=completed|3=failed
    error_message:      Optional[str]  = None
    record_count:       Optional[int]  = None
    processing_time:    Optional[int]  = None  # ms


class GGDatasourceBulkCreate(BaseModel):
    datasources: List[GGDatasourceCreate] = Field(..., min_length=1, max_length=100)
