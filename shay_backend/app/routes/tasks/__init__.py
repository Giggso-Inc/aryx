"""
Task routes for CRUD operations and task management.

This used to be a single 2,547-line module. It is now a package split by
endpoint (list_tasks, count, stats, create, detail, update, delete,
assignment, thread_tasks), with private cross-cutting helpers in
_shared/_details/_history and background-task notification logic in
notifications_email/notifications_dispatch. This ``__init__`` combines
every submodule router into one ``router`` so external callers
(``main.py``, tests) keep working exactly as before via
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

from . import (
    assign,
    count,
    create,
    delete,
    detail,
    list_tasks,
    stats,
    status_update,
    thread_create,
    thread_detail,
    thread_status,
    update,
)

router = APIRouter()
# NOTE ON ORDER: count.router's literal `GET /count` and stats.router's
# literal `GET /stats/overview` must be registered before detail.router's
# (and update/delete's) dynamic `GET|PUT|DELETE /{task_id}` — FastAPI
# matches routes in registration order, and a dynamic single-segment path
# would otherwise swallow `/count` as task_id="count" (this is the exact
# order the original monolithic tasks.py declared these routes in).
router.include_router(list_tasks.router)
router.include_router(count.router)
router.include_router(stats.router)
router.include_router(create.router)
router.include_router(detail.router)
router.include_router(update.router)
router.include_router(delete.router)
router.include_router(assign.router)
router.include_router(status_update.router)
router.include_router(thread_detail.router)
router.include_router(thread_status.router)
router.include_router(thread_create.router)

__all__ = ["router"]
