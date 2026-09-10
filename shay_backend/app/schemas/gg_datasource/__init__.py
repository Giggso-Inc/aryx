"""
GGDatasource schemas package (re-exports).

This package replaces the former single-file app/schemas/gg_datasource.py,
split into create/responses/upload/connection/embedding modules to keep
each file under the Raven 150-line style limit. All public names are
re-exported here so existing `from app.schemas.gg_datasource import X`
imports keep working unchanged.
"""

from .create import (
    ScopeLevel,
    GGDatasourceCreate,
    GGDatasourceUpdate,
    ProcessingStatusUpdate,
    GGDatasourceBulkCreate,
)
from .responses import (
    GGDatasourceResponse,
    GGDatasourceList,
    ResolvedDatasourcesResponse,
    GGDatasourceBulkResponse,
    GGDatasourceStats,
)
from .upload import FileUploadResponse, FileUploadBulkResponse
from .connection import (
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    DatasourceConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceBulkConnectionResponse,
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
)
from .embedding import (
    GGEmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    RegenerateEmbeddingResponse,
)

__all__ = [
    "ScopeLevel",
    "GGDatasourceCreate",
    "GGDatasourceUpdate",
    "ProcessingStatusUpdate",
    "GGDatasourceBulkCreate",
    "GGDatasourceResponse",
    "GGDatasourceList",
    "ResolvedDatasourcesResponse",
    "GGDatasourceBulkResponse",
    "GGDatasourceStats",
    "FileUploadResponse",
    "FileUploadBulkResponse",
    "DatasourceTypeCount",
    "DatasourceTypeCountResponse",
    "DatasourceConnectionResponse",
    "DatasourceConnectionRequest",
    "DatasourceBulkConnectionResponse",
    "DatasourceProcessingRequest",
    "DatasourceProcessingResponse",
    "GGEmbeddingStatusResponse",
    "MLWebhookRequest",
    "MLWebhookResponse",
    "RegenerateEmbeddingResponse",
]
