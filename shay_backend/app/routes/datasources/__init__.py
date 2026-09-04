"""
Datasource routes for managing data sources from various platforms.

This used to be a single 5,500+ line module. It is now a package split by
resource area (crud, upload, bulk, processing, connections, embedding),
with private cross-cutting helpers in ``_shared.py``. This ``__init__``
combines every submodule router into one ``router`` so external callers
(``main.py``, tests) keep working exactly as before, and re-exports the
handful of helper names that other modules import directly from
``app.routes.datasources``.
"""

from fastapi import APIRouter

from . import bulk, connections, crud, embedding, processing, upload
from ._shared import (
    _aryx_ingestion_status_for,
    clean_metadata,
    generate_datasource_metadata,
    handle_vault_integration,
)

router = APIRouter()
router.include_router(crud.router)
router.include_router(upload.router)
router.include_router(bulk.router)
router.include_router(processing.router)
router.include_router(connections.router)
router.include_router(embedding.router)

__all__ = [
    "router",
    "clean_metadata",
    "generate_datasource_metadata",
    "handle_vault_integration",
]
