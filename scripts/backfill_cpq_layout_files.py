#!/usr/bin/env python3
"""One-time backfill: seed aryx_cpq_layout_file from the 5 existing
config_layouts/*.txt files, for every REAL (workspace_id, catalog_prefix)
pair this environment's own data actually has -- never guessed.

CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md Phase 2. Per §7.1
(resolved): layout files are strictly per-workspace, so this seeds one
independent row per real (workspace_id, catalog_prefix) pair, not one
shared row per catalog.

Ground-truthing method (matches how `_catalog_prefix()` itself derives a
catalog from ingested data): for each real non-default workspace, list its
distinct ontology types (`CpqRdb.list_ontology_types`), derive each type's
catalog_prefix via the same `aryx.cpq.catalog_naming._catalog_prefix()`
regex the live engine already uses for catalog scoping, then resolve that
prefix against the local `config_layouts/` directory using the EXISTING,
already-proven `LocalDirLayoutFileSource` manifest+fuzzy-match logic --
reusing the exact matching this environment already trusts at read time,
rather than reinventing a second matching algorithm for the backfill.

Usage:
    python3 -m scripts.backfill_cpq_layout_files [--apply]

Without --apply, this only prints what it WOULD do (dry run, default) --
matches this session's established discipline of ground-truthing before
any destructive/data-writing action.
"""
from __future__ import annotations

import argparse
import logging
import sys

from aryx.config import get_settings
from aryx.cpq.catalog_naming import _catalog_prefix
from aryx.cpq.layout_source import LocalDirLayoutFileSource
from aryx.cpq.rdb.rdb import get_cpq_rdb
from aryx.cpq_ingestion.layout_store import store_layout_file
from aryx.queries import load
from aryx.store.pool import get_pool

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_cpq_layout_files")


def _real_workspace_ids(dsn: str) -> list[int]:
    """Every non-default workspace that exists in this environment today --
    same query T11's audit used to ground-truth /admin/workspaces/nuke."""
    pool = get_pool(dsn)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(load("select_non_default_workspace_ids"))
        return [row[0] for row in cur.fetchall()]


def _catalog_prefixes_for_workspace(workspace_id: int) -> set[str]:
    """Distinct real catalog_prefix values this workspace's own ingested
    ontology types actually derive to -- empty results from
    `_catalog_prefix()` (no 'Bm<Upper>' marker) are dropped; "" is never a
    valid catalog to seed a layout row under."""
    rdb = get_cpq_rdb()
    try:
        types = rdb.list_ontology_types(workspace_id)
    except Exception:
        logger.warning("workspace_id=%d: list_ontology_types failed", workspace_id, exc_info=True)
        return set()
    prefixes = {_catalog_prefix(t) for t in types}
    prefixes.discard("")
    return prefixes


def run(apply: bool) -> int:
    settings = get_settings()
    dsn = settings.effective_dsn()
    local_source = LocalDirLayoutFileSource()  # reads ARYX_CPQ_LAYOUT_DIR

    workspace_ids = _real_workspace_ids(dsn)
    logger.info("found %d real non-default workspace(s): %s", len(workspace_ids), workspace_ids)

    planned: list[tuple[int, str, str]] = []  # (workspace_id, catalog_prefix, filename-ish for logging)
    for ws in workspace_ids:
        prefixes = _catalog_prefixes_for_workspace(ws)
        if not prefixes:
            continue
        for prefix in sorted(prefixes):
            content = local_source.get(prefix, ws)  # workspace_id ignored by LocalDirLayoutFileSource
            if content is None:
                continue  # no local layout file matches this real catalog_prefix -- nothing to backfill
            planned.append((ws, prefix, content))

    if not planned:
        logger.info("nothing to backfill: no real (workspace_id, catalog_prefix) pair "
                     "matched a local config_layouts/ file")
        return 0

    logger.info("%d real (workspace_id, catalog_prefix) pair(s) matched a local layout file:", len(planned))
    for ws, prefix, content in planned:
        logger.info("  workspace_id=%d catalog_prefix=%r (%d bytes)", ws, prefix, len(content))

    if not apply:
        logger.info("dry run only -- pass --apply to actually write these %d row(s)", len(planned))
        return 0

    for ws, prefix, content in planned:
        stored_prefix = store_layout_file(
            content.encode("utf-8"), f"{prefix}.txt",
            workspace_id=ws, dsn=dsn, catalog_prefix=prefix,
        )
        logger.info("stored workspace_id=%d catalog_prefix=%r", ws, stored_prefix)

    logger.info("backfill complete: %d row(s) written", len(planned))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                         help="Actually write rows (default: dry run, print only).")
    args = parser.parse_args()
    return run(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
