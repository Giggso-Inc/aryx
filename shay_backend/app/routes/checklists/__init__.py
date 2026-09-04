"""
Checklist routes for managing task checklists

This module defines FastAPI routes for comprehensive checklist management including
creation, updates, completion tracking, and reordering.

File: app/routes/checklists/
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Bulk checklist creation and management
- Individual checklist operations
- Completion tracking with user attribution
- Dynamic reordering of checklist items
- Comprehensive access control and validation

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 530-line app/routes/checklists.py. It is now a package split
by resource area (task-scoped vs checklist-item-scoped endpoints), combined
into one `router` below so that `from app.routes.checklists import router`
(used by app/routes/__init__.py's route registration) needs zero changes.

Route registration order: none of this module's paths collide (every route
template differs in path-segment shape — e.g. /task/{task_id}/checklists
vs /task/{task_id}/checklists/reorder vs /checklist/{checklist_id} vs
/checklist/{checklist_id}/complete — so FastAPI's registration-order
matching never has to disambiguate between them), so the two submodules
below are combined without needing to replicate the original file's exact
declaration order.
"""

from fastapi import APIRouter

from . import item_ops
from . import task_meta
from . import task_ops
from .helpers import get_checklist_with_access, get_task_with_workspace_access

router = APIRouter()
router.include_router(task_ops.router)
router.include_router(task_meta.router)
router.include_router(item_ops.router)

__all__ = ["router", "get_checklist_with_access", "get_task_with_workspace_access"]
