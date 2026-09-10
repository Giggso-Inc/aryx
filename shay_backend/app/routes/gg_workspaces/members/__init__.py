"""
Workspace-level GGMember endpoints: list, add, update, remove members, and
resolve a user's effective role at thread/channel/workspace scope.

Split from app/routes/gg_workspaces/members.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) into one
submodule per endpoint, sharing UUID/response helpers from ../helpers.py.
This ``__init__`` combines every submodule router into one ``router`` so
external callers keep working via ``from app.routes.gg_workspaces.members
import router``.

Registration order matches the original module: list, add, update, remove,
effective_role.
"""

from fastapi import APIRouter

from . import add, effective_role, list, remove, update

router = APIRouter()
router.include_router(list.router)
router.include_router(add.router)
router.include_router(update.router)
router.include_router(remove.router)
router.include_router(effective_role.router)

__all__ = ["router"]
