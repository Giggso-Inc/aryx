"""
Task routes for CRUD operations and task management.

This used to be a single 2,547-line module. It is now a package split by
resource area (crud, listing, assignment, thread_tasks), with private
cross-cutting helpers in _shared/_details/_history and background-task
notification logic in notifications_email/notifications_dispatch. This
``__init__`` combines every submodule router into one ``router`` so
external callers (``main.py``, tests) keep working exactly as before via
``from app.routes.tasks import router``.

File: app/routes/tasks/__init__.py (formerly app/routes/tasks.py)
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Full CRUD operations for tasks
- Status management with new values (Open, In Progress, On Hold, Close)
- Priority management (Low, Medium, High, Critical, Blocker)
- Checklist integration during task creation
- Thread-specific task management
- Comprehensive access control and validation
"""

from fastapi import APIRouter

from . import assignment, crud, listing, thread_tasks

router = APIRouter()
# NOTE ON ORDER: listing.router's literal `GET /count` and `GET /stats/overview`
# must be registered before crud.router's dynamic `GET /{task_id}` — FastAPI
# matches routes in registration order, and a dynamic single-segment path
# would otherwise swallow `/count` as task_id="count" (this is the exact
# order the original monolithic tasks.py declared these routes in).
router.include_router(listing.router)
router.include_router(crud.router)
router.include_router(assignment.router)
router.include_router(thread_tasks.router)

__all__ = ["router"]
