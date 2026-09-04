"""
User management routes for company administrators.

This module provides API endpoints for managing users within companies, including
listing users with advanced filtering, sorting, and pagination capabilities.
It handles user CRUD operations and ensures proper access control through
authentication middleware.

Author: Karthick Chandrasekar, Pranhav Vimal
Date: 2025-08-14, 2025-01-27
Version: 1.0.0, 1.1.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 658-line app/routes/users.py. It is now a package of
submodules by endpoint/sub-area, combined into one `router` below so that
`from app.routes import users` / `users.router` (used by main.py's route
registration) needs zero changes.

Route registration order: none of this file's 8 routes collide (every path
template differs in either its literal segments or its segment count -- e.g.
GET /company/{company_id}/users vs GET /company/{company_id}/users/{user_id}
vs GET /company/{company_id}/stats vs GET /search), so registration order
here is not load-bearing. It is preserved anyway, matching the original
file's declaration order, as a courtesy.
"""

from fastapi import APIRouter

from . import list_users
from . import detail
from . import stats
from . import search
from . import invitations
from . import bulk

router = APIRouter()
router.include_router(list_users.router)
router.include_router(detail.router)
router.include_router(stats.router)
router.include_router(search.router)
router.include_router(invitations.router)
router.include_router(bulk.router)

__all__ = ["router"]
