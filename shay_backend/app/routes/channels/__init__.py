"""
Channel routes for CRUD operations with automatic workspace management

Author: Karthick Chandrasekar, Pranhav Vimal
Date: 2025-08-14, 2025-01-27
Version: 1.0.0, 1.1.0

Recent Changes:
Author: Pranhav Vimal
Date: 2025-01-27
Version: 1.2.0
- Added agent_count, agent_names, workflow_count, and RCA fields to channel responses
- Enhanced list_company_channels and list_my_channel_memberships endpoints with additional metadata

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5): this used to be a
single 2,630-line app/routes/channels.py. It is now a package of submodules
by resource/sub-area, combined into one `router` below so that
`from app.routes.channels import router` (used by the app's route
registration) needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and a single-segment dynamic
path like GET /{channel_id} would otherwise swallow literal single-segment
paths such as GET /company or GET /tags. The static-path submodules
(list_my, list_message, list_company, list_memberships, tags) are therefore
included BEFORE the dynamic-path submodules (detail, members_*, mutate),
preserving the original file's endpoint declaration order exactly.
"""

from fastapi import APIRouter

from . import create
from . import list_my
from . import list_message
from . import list_company
from . import list_memberships
from . import tags
from . import tags_workspaces
from . import detail
from . import detail_access
from . import members_single
from . import members_single_list
from . import members_admin
from . import mutate
from . import mutate_delete
from . import members_bulk
from .helpers import validate_uuid, get_channel_admins

router = APIRouter()
router.include_router(create.router)
router.include_router(list_my.router)
router.include_router(list_message.router)
router.include_router(list_company.router)
router.include_router(list_memberships.router)
router.include_router(tags.router)
router.include_router(tags_workspaces.router)
router.include_router(detail.router)
router.include_router(detail_access.router)
router.include_router(members_single.router)
router.include_router(members_single_list.router)
router.include_router(members_admin.router)
router.include_router(mutate.router)
router.include_router(mutate_delete.router)
router.include_router(members_bulk.router)

__all__ = ["router", "validate_uuid", "get_channel_admins"]
