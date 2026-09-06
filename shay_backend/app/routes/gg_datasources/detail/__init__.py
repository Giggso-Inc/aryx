"""
Single-resource CRUD by ID plus file download/view:

  GET    /{datasource_id}
  GET    /{datasource_id}/download
  PUT    /{datasource_id}
  DELETE /{datasource_id}
  PUT    /{datasource_id}/status   (ML callback)

Must be registered after the literal-path submodules in the parent package
(upload, create_from_upload, create, query, embedding, processing) — its
GET/PUT/DELETE /{datasource_id} routes would otherwise swallow their
single-segment literal paths (e.g. GET /stats, GET /count).

Split into one module per endpoint (Raven style-compliance, wave B4) —
previously a single 166-line detail.py. Combined here via
router.include_router() preserving the original declaration order so
`from . import detail; router.include_router(detail.router)` in the
package __init__.py needs no changes.
"""

from fastapi import APIRouter

from . import download
from . import get
from . import status
from . import update

router = APIRouter()
router.include_router(get.router)
router.include_router(download.router)
router.include_router(update.router)
router.include_router(status.router)
