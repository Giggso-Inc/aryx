"""
Plain file-upload endpoints (no GGDatasource row created) plus the two
supporting lookups:

  GET    /supported-log-types
  GET    /environment
  POST   /upload
  POST   /upload/bulk

`_upload_single_file` / `_build_config_from_upload` (in `._helpers`) are
also imported by `app.routes.gg_datasources.create_from_upload`, which
builds a GGDatasource row on top of an upload.

Split into one module per endpoint (Raven style-compliance, wave B4) —
previously a single 175-line upload.py. Combined here via
router.include_router() so `from . import upload;
router.include_router(upload.router)` in the package __init__.py needs no
changes, and re-exports `_upload_single_file` / `_build_config_from_upload`
so `from .upload import ...` in create_from_upload.py also needs no changes.
"""

from fastapi import APIRouter

from . import bulk
from . import misc
from . import single
from ._helpers import _build_config_from_upload, _upload_single_file

router = APIRouter()
router.include_router(misc.router)
router.include_router(single.router)
router.include_router(bulk.router)

__all__ = ["router", "_upload_single_file", "_build_config_from_upload"]
