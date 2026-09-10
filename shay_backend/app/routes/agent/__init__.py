"""
AI Agent routes for webhook callbacks and AI processing management

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5): this used to be a
single 370-line app/routes/agent.py. It is now a package of submodules by
endpoint (callback, status, health, stats, trigger + its process_ai_request
background-task helper), combined into one `router` below so that
`from .agent import router as agent_router` (used by app/routes/__init__.py)
needs zero changes.

Route registration order matches the original file's declaration order:
POST /callback, POST /status, GET /health, GET /stats,
POST /trigger/{message_id}. None of these paths collide (each has a
distinct literal first segment, or in trigger's case a dynamic segment
under a distinct literal prefix), so registration order has no
routing-behavior effect here — it is preserved anyway per the wave B5 plan.
"""

from fastapi import APIRouter

from . import callback
from . import status
from . import health
from . import stats
from . import trigger

router = APIRouter()
router.include_router(callback.router)
router.include_router(status.router)
router.include_router(health.router)
router.include_router(stats.router)
router.include_router(trigger.router)

__all__ = ["router"]
