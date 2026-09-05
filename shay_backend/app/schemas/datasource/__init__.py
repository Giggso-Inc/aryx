"""
Datasource schemas for request/response validation.

This package replaces the former single-file app/schemas/datasource.py
(445 lines) as part of Raven Phase 5a file-size compliance. It is split
into:

- config.py           -- shared DatasourceConfig storage-config model
- create.py           -- public-API create request schemas (channel-scoped)
- create_internal.py  -- internal-API create request schemas (thread-scoped)
- update.py           -- update request schema
- responses.py    -- single/list/bulk/with-relations response schemas
- stats.py        -- statistics and type-count schemas
- processing.py    -- processing request/response + per-storage-type create schemas
- upload.py        -- file-upload response + create-from-upload schemas
- connections.py    -- connect/disconnect request+response schemas
- embedding.py      -- embedding status + ML webhook schemas

Every class below is re-exported here so `from app.schemas.datasource
import X` continues to work unchanged for every existing caller,
including app/routes/datasources/{crud,upload,bulk,connections,embedding,
processing}.py.
"""

from .config import DatasourceConfig
from .create import DatasourceCreate, DatasourceBulkCreate
from .create_internal import DatasourceCreateInternal, DatasourceBulkCreateInternal
from .update import DatasourceUpdate
from .responses import (
    DatasourceResponse,
    DatasourceList,
    DatasourceBulkResponse,
    DatasourceWithRelationsResponse,
    DatasourceListWithRelations,
)
from .stats import (
    DatasourceStats,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
)
from .processing import (
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
    LocalDatasourceCreate,
    CloudDatasourceCreate,
    AppDatasourceCreate,
)
from .upload import (
    FileUploadResponse,
    FileUploadBulkResponse,
    DatasourceFromUpload,
    DatasourceFromUploadBulk,
)
from .connections import (
    DatasourceConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceBulkConnectionResponse,
)
from .embedding import (
    EmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    RegenerateEmbeddingResponse,
)

__all__ = [
    "DatasourceConfig",
    "DatasourceCreate",
    "DatasourceBulkCreate",
    "DatasourceCreateInternal",
    "DatasourceBulkCreateInternal",
    "DatasourceUpdate",
    "DatasourceResponse",
    "DatasourceList",
    "DatasourceBulkResponse",
    "DatasourceWithRelationsResponse",
    "DatasourceListWithRelations",
    "DatasourceStats",
    "DatasourceTypeCount",
    "DatasourceTypeCountResponse",
    "DatasourceProcessingRequest",
    "DatasourceProcessingResponse",
    "LocalDatasourceCreate",
    "CloudDatasourceCreate",
    "AppDatasourceCreate",
    "FileUploadResponse",
    "FileUploadBulkResponse",
    "DatasourceFromUpload",
    "DatasourceFromUploadBulk",
    "DatasourceConnectionResponse",
    "DatasourceConnectionRequest",
    "DatasourceBulkConnectionResponse",
    "EmbeddingStatusResponse",
    "MLWebhookRequest",
    "MLWebhookResponse",
    "RegenerateEmbeddingResponse",
]
