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
(detail, invitations, accept), preserving the original file's endpoint
declaration order exactly.
"""

from fastapi import APIRouter

from . import list_company
from . import detail
from . import invitations
from . import accept

router = APIRouter()
router.include_router(list_company.router)
router.include_router(detail.router)
router.include_router(invitations.router)
router.include_router(accept.router)

__all__ = ["router"]
