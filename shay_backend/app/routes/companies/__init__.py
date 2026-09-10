"""
Company routes for CRUD operations and management.

This module provides API endpoints for company management operations including
company creation, updates, user invitations, and company statistics. It handles
company-user relationships and ensures proper access control through authentication.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 647-line app/routes/companies.py. It is now a package of
submodules by resource/sub-area, combined into one `router` below so that
`from app.routes.companies import router` needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{company_id} would otherwise swallow literal single-segment
paths such as GET /test or GET /my. The static-path submodule
(list_company) is therefore included BEFORE the dynamic-path submodules
(detail_*, invite, invitations, accept), preserving the original file's
endpoint declaration order exactly.

Update (wave B4): detail.py (156 lines, GET/PUT on /{company_id} + GET
/{company_id}/stats) was split one-endpoint-per-file into detail_get.py,
detail_update.py, and detail_stats.py. invitations.py (343 lines, POST
/{company_id}/invite + GET /{company_id}/invitations) was split into
invite.py (the POST) and invitations.py (the GET, further split into
invitations_query.py and invitations_response.py helper modules).
"""

from fastapi import APIRouter

from . import accept
from . import detail_get
from . import detail_stats
from . import detail_update
from . import invitations
from . import invite
from . import list_company

router = APIRouter()
router.include_router(list_company.router)
router.include_router(detail_get.router)
router.include_router(detail_update.router)
router.include_router(detail_stats.router)
router.include_router(invite.router)
router.include_router(invitations.router)
router.include_router(accept.router)

__all__ = ["router"]
