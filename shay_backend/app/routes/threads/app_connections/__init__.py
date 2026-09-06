"""
Thread-level app-account management (mounted at /api/v1/threads):
  GET/POST     /{thread_id}/app-connections
  PUT/DELETE   /{thread_id}/app-connections/{connection_id}

Split from app/routes/threads/app_connections.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) into one submodule
per endpoint, sharing the GGAppConnectionResponse-building helper via
serializers.py. Registration order matches the original module: list,
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
