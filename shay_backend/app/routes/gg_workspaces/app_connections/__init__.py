"""
Workspace-level GGAppConnection endpoints: list, connect, update, and
disconnect apps at workspace scope. Gmail is treated as personal OAuth and
gets a per-user visibility/uniqueness carve-out throughout.

Split from app/routes/gg_workspaces/app_connections.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
into one submodule per endpoint, sharing UUID/response helpers from
../helpers.py. Registration order matches the original module: list,
connect, update, disconnect.
"""

from fastapi import APIRouter

from . import connect, disconnect, list, update

router = APIRouter()
router.include_router(list.router)
router.include_router(connect.router)
router.include_router(update.router)
router.include_router(disconnect.router)

__all__ = ["router"]
