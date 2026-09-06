"""
Upload-and-create endpoints (upload a file to storage AND create the
GGDatasource row in one call), plus their bulk counterpart:

  POST   /from-upload
  POST   /from-upload/bulk

Split into one module per endpoint plus a shared metadata/vault helper
(Raven style-compliance, wave B4) — previously a single 293-line
create_from_upload.py. See single.py and bulk.py for the "stated exception"
on why each handler still runs a bit longer than a typical endpoint.
Combined here via router.include_router() so `from . import
create_from_upload; router.include_router(create_from_upload.router)` in
the package __init__.py needs no changes.
"""

from fastapi import APIRouter

from . import bulk
from . import single

router = APIRouter()
router.include_router(single.router)
router.include_router(bulk.router)
