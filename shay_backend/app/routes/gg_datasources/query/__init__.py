"""
Read/list endpoints (must be registered before app.routes.gg_datasources.detail,
whose GET /{datasource_id} would otherwise swallow these literal paths):

  GET    /resolved   inheritance-aware fetch across workspace/channel/thread/message
  GET    /stats      datasource statistics (scope-filtered)
  GET    /count      connected datasource count by storage type
  GET    /           list with filters + pagination

Split into one module per endpoint (Raven style-compliance, wave B4) —
each was previously a section of a single 214-line query.py. Combined here
via router.include_router() preserving the original declaration order so
`from . import query; router.include_router(query.router)` in the package
__init__.py needs no changes.
"""

from fastapi import APIRouter

from . import count
from . import list_all
from . import resolved
from . import stats

router = APIRouter()
router.include_router(resolved.router)
router.include_router(stats.router)
router.include_router(count.router)
router.include_router(list_all.router)
