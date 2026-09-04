"""
GGDatasource routes — unified datasource management across
workspace / channel / thread / message scopes.

Prefix: /api/v1/gg-datasources

Endpoints
─────────
  GET    /supported-log-types           list supported log types
  GET    /environment                   environment/vault debug config
  POST   /upload                        upload a single file (no DB row)
  POST   /upload/bulk                   upload multiple files (no DB rows)
  POST   /from-upload                   upload file + create GGDatasource row
  POST   /from-upload/bulk              upload files + create multiple GGDatasource rows
  POST   /bulk                          bulk-create from JSON payloads
  POST   /                              create a single datasource
  GET    /resolved                      all datasources visible at a scope (with inheritance)
  GET    /stats                         datasource statistics (scope-filtered)
  GET    /count                         connected datasource count by type
  GET    /                              list datasources (filter by level + scope)
  GET    /embedding-status/{scope_level}/{scope_id}  embedding status for a scope
  POST   /embedding/webhook             ML embedding completion webhook
  POST   /embedding/regenerate/{datasource_id}  re-trigger embedding
  POST   /process                       trigger background processing
  POST   /bulk-connection               bulk connect / disconnect
  GET    /{datasource_id}               get by ID
  GET    /{datasource_id}/download      download / view file
  PUT    /{datasource_id}               update metadata / flags
  DELETE /{datasource_id}               soft-delete (is_active = False)
  PUT    /{datasource_id}/status        update processing / embedding status (ML callback)
  POST   /{datasource_id}/connect       connect a datasource
  POST   /{datasource_id}/disconnect    disconnect a datasource
  GET    /{datasource_id}/connection-status  get connection status

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 1,493-line app/routes/gg_datasources.py. It is now a package
of submodules by resource/sub-area, combined into one `router` below so that
`from .gg_datasources import router as gg_datasources_router` (used by
app/routes/__init__.py) needs zero changes.

Route registration ORDER matters here, same as app/routes/channels/: FastAPI/
Starlette matches routes in registration order for a given HTTP method, and
the single-segment dynamic paths in `detail` (GET/PUT/DELETE /{datasource_id})
would otherwise swallow literal single-segment paths such as GET /stats or
GET /count. The static-path submodules (upload, create_from_upload, create,
query, embedding, processing) are therefore included BEFORE the dynamic-path
submodules (detail, connection), preserving the original file's endpoint
declaration order exactly.
"""

from fastapi import APIRouter

from . import connection
from . import create
from . import create_from_upload
from . import detail
from . import embedding
from . import processing
from . import query
from . import upload
from .response import (
    _get_external_view_url,
    _get_google_drive_file_id,
    _get_media_type,
    _get_storage_file_path,
    _to_response,
)

router = APIRouter()
router.include_router(upload.router)
router.include_router(create_from_upload.router)
router.include_router(create.router)
router.include_router(query.router)
router.include_router(embedding.router)
router.include_router(processing.router)
router.include_router(detail.router)
router.include_router(connection.router)

__all__ = [
    "router",
    "_get_media_type",
    "_get_storage_file_path",
    "_get_external_view_url",
    "_get_google_drive_file_id",
    "_to_response",
]
