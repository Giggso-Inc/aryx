"""
Template routes for managing template files.

Prefix: /api/v1/template

This package provides API endpoints for:
- Fetching template files from the template directory
- Listing template files
- Template file operations (read, download, upload, update, delete)
- Database template-record management (list / get)

Endpoints
─────────
  GET    /files                          list template files on disk
  GET    /files/{filename}                get a template file's content
  GET    /content/{template_id}           get template content by DB template_id
  GET    /files/{filename}/download       download a template file
  POST   /files/upload                    upload a template file + create DB record
  PUT    /files/{identifier}              update a template file + DB record
  DELETE /files/{identifier}              delete a template file + DB record
  GET    /                                list template DB records (paginated)
  GET    /{identifier}                    get a template DB record

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 881-line app/routes/template.py. It is now a package of
submodules by resource/sub-area, combined into one `router` below so that
`from app.routes import template` + `template.router` (used by main.py's
`app.include_router(template.router, prefix="/api/v1/template", ...)`)
needs zero changes.

Route registration order matches the original file's endpoint declaration
order exactly: the /files/* and /content/* literal-first-segment submodules
are registered before db_detail's GET /{identifier}, so that single dynamic
segment never has a chance to swallow a literal sibling (same precedent as
channels/ and gg_datasources/), even though today's endpoint set does not
actually collide.

Update (Raven style-compliance wave B4): files_get.py (175 lines, GET
/files/{filename} + GET /content/{template_id}) was split one-endpoint-per-
file into files_get.py and files_content.py. files_mutate.py (194 lines,
PUT + DELETE on /files/{identifier}) was split into files_update.py and
files_delete.py, in the same PUT-then-DELETE order as the original file.
"""

from fastapi import APIRouter

from . import db_detail
from . import db_list
from . import files_content
from . import files_delete
from . import files_download
from . import files_get
from . import files_list
from . import files_update
from . import files_upload
from .helpers import (
    generate_template_id,
    get_platform_from_template_id,
    get_template_type_from_id,
    is_valid_template_id_format,
    validate_template_id_for_platform,
    validate_template_id_for_type,
)

router = APIRouter(tags=["Templates"])
router.include_router(files_list.router)
router.include_router(files_get.router)
router.include_router(files_content.router)
router.include_router(files_download.router)
router.include_router(files_upload.router)
router.include_router(files_update.router)
router.include_router(files_delete.router)
router.include_router(db_list.router)
router.include_router(db_detail.router)

__all__ = [
    "router",
    "generate_template_id",
    "get_template_type_from_id",
    "get_platform_from_template_id",
    "validate_template_id_for_type",
    "validate_template_id_for_platform",
    "is_valid_template_id_format",
]
