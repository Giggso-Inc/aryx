"""
Thread CRUD endpoints (mounted at /api/v1/threads):
  POST   /                   create thread
  GET    /                   list threads (channel_id required)
  GET    /{thread_id}        get thread
  PUT    /{thread_id}        update thread
  DELETE /{thread_id}        delete thread (admin only)

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) into one submodule per
endpoint, sharing the ThreadResponse-building helper via serializers.py.
This ``__init__`` combines every submodule router into one ``router`` so
external callers keep working via ``from app.routes.threads.crud import
router``.

Registration order matches the original module: create, list (both at the
literal path "/"), then get/update/delete (all at the dynamic
"/{thread_id}") — static paths already register before the dynamic ones.
"""

from fastapi import APIRouter

from . import create, delete, get, list, update

router = APIRouter()
router.include_router(create.router)
router.include_router(list.router)
router.include_router(get.router)
router.include_router(update.router)
router.include_router(delete.router)

__all__ = ["router"]
