"""Layout-file resolution: Oracle ADB / Postgres, per-workspace.

CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md Phase 5: replaces
the local-directory `config_layouts/` default this module used before
cutover. `LocalDirLayoutFileSource` and its manifest/fuzzy-match logic
are gone -- `git log -p` on this file has them if ever needed for
reference (e.g. to understand the real catalog_prefix naming quirks
`scripts/backfill_cpq_layout_files.py` had to account for during the
one-time migration).
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

# Sentinel `variant` for a layout export that names no flow of its own (and
# for every pre-variant row). NOT NULL by design: Oracle stores '' as NULL
# and a NULL never conflicts in a unique key. The SQL migration
# 0050_cpq_layout_variant.sql repeats this literal as the column default.
DEFAULT_LAYOUT_VARIANT = "default"


def layout_cache_key(
    workspace_id: int, catalog_prefix: str, variant: str = DEFAULT_LAYOUT_VARIANT,
) -> tuple:
    """Cache key for one layout. The sentinel variant keeps the historical
    (workspace_id, catalog_prefix) key, so single-layout catalogs are
    byte-identical to before; any other variant appends itself."""
    if variant == DEFAULT_LAYOUT_VARIANT:
        return (workspace_id, catalog_prefix)
    return (workspace_id, catalog_prefix, variant)


class LayoutFileSource(Protocol):
    """Resolves a catalog's native-UI layout export to its raw file text,
    scoped to a specific workspace."""

    def get(
        self, catalog_name: str, workspace_id: int,
        variant: str = DEFAULT_LAYOUT_VARIANT,
    ) -> str | None:
        """Return the layout file's raw text for catalog_name in
        workspace_id (one `variant`), or None.

        Sources may also offer ``variant_keys(catalog_name, workspace_id)``
        (stored variants, oldest upload first); it is optional."""
        ...


class OracleLayoutFileSource:
    """Reads layout files from `aryx_cpq_layout_file` (Oracle ADB CLOB /
    Postgres TEXT, via the shared pool), keyed by (workspace_id,
    catalog_prefix) -- uploaded per-workspace, replacing the old baked-in
    `config_layouts/` directory.

    CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: strict
    per-workspace isolation is enforced in the SQL itself (`WHERE
    workspace_id = %s`), not by holding a per-workspace instance -- a
    single process-wide instance is enough; there is no per-call state
    that could leak between workspaces.

    The connection pool is resolved lazily, on first `.get()` call, not
    in `__init__` -- this class is instantiated once at `cpq/
    engine_caches.py` module-import time (see `_DEFAULT_LAYOUT_FILE_
    SOURCE`), which runs on every `import aryx.cpq.engine` across the
    whole codebase, including test collection in environments with no
    live database reachable. Opening a pool eagerly there would make
    every such import fail; deferring it to the first real lookup means
    an environment that never actually loads a layout (most unit tests)
    never touches the database at all.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            from aryx.store.pool import get_pool  # noqa: PLC0415 -- lazy,
            # avoids importing the store layer at cpq/ module-import time.
            self._pool = get_pool(self._dsn)
        return self._pool

    def variant_keys(self, catalog_name: str, workspace_id: int) -> list[str]:
        """Stored variant keys for one catalog, oldest upload first."""
        if not catalog_name:
            return []
        from aryx.queries import load  # noqa: PLC0415 -- see _get_pool's note
        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_cpq_layout_variants"), (workspace_id, catalog_name))
                return [str(r[0]) for r in cur.fetchall()]

    def get(
        self, catalog_name: str, workspace_id: int,
        variant: str = DEFAULT_LAYOUT_VARIANT,
    ) -> str | None:
        if not catalog_name:
            return None
        from aryx.queries import load  # noqa: PLC0415 -- see _get_pool's note
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_cpq_layout_file"), (workspace_id, catalog_name, variant))
                row = cur.fetchone()
        if row is None:
            logger.warning(
                "cpq layout_source: no active layout file for "
                "workspace_id=%r catalog_prefix=%r variant=%r in "
                "aryx_cpq_layout_file -- this catalog will get no display-"
                "order/visibility signal from an uploaded layout export",
                workspace_id, catalog_name, variant,
            )
            return None
        return row[0]
