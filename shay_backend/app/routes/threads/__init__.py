"""
Thread CRUD and thread-level member / app-connection overrides.

This used to be a single 657-line module. It is now a package split by
resource area (crud, members, app_connections), matching the section
headers the original file already used internally. This ``__init__``
combines every submodule router into one ``router`` so external callers
(``main.py``, tests) keep working exactly as before via
``from app.routes.threads import router``.
"""

from fastapi import APIRouter

from . import app_connections, crud, members

router = APIRouter()
router.include_router(crud.router)
router.include_router(members.router)
router.include_router(app_connections.router)

__all__ = ["router"]
