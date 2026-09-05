"""
Datasource routes for managing data sources from various platforms.

This used to be a single 5,500+ line module, then a package of a handful of
400-1300 line files. It is now split much further by individual endpoint /
tight helper-cluster, with private cross-cutting helpers grouped by purpose
(``_vault_*``, ``_metadata_*``, ``_embedding_helpers``, ``_list_*``,
``_file_resolvers``, ``_create_*``) instead of one flat ``_shared.py``. This
``__init__`` combines every submodule router into one ``router`` so external
callers (``main.py``, tests) keep working exactly as before, and re-exports
the handful of helper names that other modules import directly from
``app.routes.datasources``.

Registration order matters only where two routes for the SAME HTTP method
could collide (a literal path vs. a dynamic ``/{datasource_id}``-shaped
path); literal-vs-literal or differing-HTTP-method ordering is free. All
literal GET paths (misc, list "/", stats/count) are registered before the
dynamic GET "/{datasource_id}", matching the original crud.py ordering.
"""

from fastapi import APIRouter

from . import (
    bulk_connection,
    bulk_create,
    bulk_create_internal,
    connect,
    connection_status,
    create,
    delete,
    disconnect,
    download_datasource,
    embedding_regenerate,
    embedding_status,
    embedding_webhook,
    from_upload,
    from_upload_bulk,
    get_datasource,
    list_datasources,
    misc,
    process_datasource,
    stats_count,
    update,
    upload_bulk_files,
    upload_single,
)
from ._embedding_helpers import _aryx_ingestion_status_for
from ._metadata_generator import generate_datasource_metadata
from ._metadata_helpers import clean_metadata
from ._vault_helpers import handle_vault_integration

router = APIRouter()
router.include_router(misc.router)
router.include_router(create.router)
router.include_router(list_datasources.router)
router.include_router(stats_count.router)
router.include_router(get_datasource.router)
router.include_router(update.router)
router.include_router(delete.router)
router.include_router(upload_single.router)
router.include_router(upload_bulk_files.router)
router.include_router(from_upload.router)
router.include_router(from_upload_bulk.router)
router.include_router(bulk_create.router)
router.include_router(bulk_create_internal.router)
router.include_router(process_datasource.router)
router.include_router(download_datasource.router)
router.include_router(bulk_connection.router)
router.include_router(connect.router)
router.include_router(disconnect.router)
router.include_router(connection_status.router)
router.include_router(embedding_status.router)
router.include_router(embedding_webhook.router)
router.include_router(embedding_regenerate.router)

__all__ = [
    "router",
    "clean_metadata",
    "generate_datasource_metadata",
    "handle_vault_integration",
]
