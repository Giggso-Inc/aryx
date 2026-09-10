"""
Approval Routes for Thread-Level Message Approvals

This package provides FastAPI routes for managing thread-level message
approval workflows: creation, listing/filtering, actions (approve/reject),
reassignment, updates, statistics, history, and soft delete. It was split
from a single 2,150-line app/routes/approvals.py into per-resource
submodules (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5).

`router` is re-exported so `from app.routes.approvals import router` (used
by app/routes/__init__.py and main.py) needs no changes.

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

API Base Path: /api/v1/approvals
"""

from fastapi import APIRouter

from . import (
    action,
    create,
    delete,
    detail,
    history,
    list as list_,
    reassign,
    stats,
    update,
)

router = APIRouter()

# Order matters: FastAPI matches routes in registration order, and the
# static "/count" and "/stats" paths must be registered before the
# "/{approval_id}" catch-all (same order the original flat file used).
router.include_router(create.router)
router.include_router(list_.router)
router.include_router(stats.router)
router.include_router(detail.router)
router.include_router(update.router)
router.include_router(action.router)
router.include_router(history.router)
router.include_router(reassign.router)
router.include_router(delete.router)

__all__ = ["router"]
