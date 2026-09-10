"""
Thread-level member management (mounted at /api/v1/threads):
  GET/POST     /{thread_id}/members
  PUT/DELETE   /{thread_id}/members/{user_id}

Split from app/routes/threads/members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) into one submodule per
endpoint, sharing the MemberResponse-building helper via serializers.py.
Registration order matches the original module: list, add, update, remove.
"""

from fastapi import APIRouter

from . import add, list, remove, update

router = APIRouter()
router.include_router(list.router)
router.include_router(add.router)
router.include_router(update.router)
router.include_router(remove.router)

__all__ = ["router"]
