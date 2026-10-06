"""One-off backfill: give already-ingested CPQ entities their display names.

Background (docs/ingestion/CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md): the
raw-graph CPQ XML path used to leave Oracle CPQ display text in separate
wrapper entities (``<label><en>..``, ``<bm_name><en>..``, ``<name><en>..``)
instead of on the owning family/model/attribute, so Ask showed numeric ids
("17691416877") and "0" for every config attribute. New ingests are fixed at
the source (raw_graph/value_wrapper.py); this repairs workspaces confirmed
before that fix (1097, 1126 at minimum).

Approach (planning is pure, see raw_graph/display_backfill.py):
  1. Read every entity's attributes, its raw XML tag (aryx_landed_record.
     source_dataset of its members) and the workspace's CONTAINS edges.
  2. Plan: fold each locale-wrapper entity's value onto every parent, then
     fill ``name`` (variable-name shape) and ``display_label`` (human text).
  3. --apply: update changed entities in committed chunks, delete the now
     redundant wrapper entities + their relationships (chunked), then
     rebuild the curated graph. Oracle graph tables are pre-cleared in
     committed chunks first -- the store's own clear() is one transaction
     and exhausted undo (ORA-30036) on a 2.2M-row workspace on 2026-10-05.

Safety: dry-run by default (prints the plan, touches nothing). Review it,
then pass --apply. --keep-wrappers skips the wrapper deletion. --rebuild-only
retries just the graph rebuild. Not wired into startup or migrations.

Run this with no ingest job active against the workspace, during a quiet
period: the plan reads every entity once and --apply writes whole attribute
dicts back, so a concurrent ingest's writes to an entity this touches are
overwritten. On the Oracle backend, --apply also pre-clears the workspace's
graph tables before the rebuild (ORA-30036 workaround, see above), so Ask
reads an empty graph for that workspace until the rebuild finishes.

Usage:
    python scripts/backfill_cpq_display_names.py --workspace-id 1126
    python scripts/backfill_cpq_display_names.py --workspace-id 1126 --apply
    python scripts/backfill_cpq_display_names.py --workspace-id 1126 --rebuild-only
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.cpq_ingestion.constants import RAW_EDGE_CONTAINS
from aryx.cpq_ingestion.raw_graph.display_backfill import (
    BackfillPlan,
    plan_display_backfill,
    types_fully_removed,
)
from aryx.pipeline.enrich.enrich import _build_type_ancestors
from aryx.project.project_full import project_graph
from aryx.queries import load
from aryx.raven_log import raven_log
from aryx.store.entity_store import EntityStore, _dumps
from aryx.store.ontology_store import OntologyStore

_CHUNK = 5_000
_GRAPH_CLEAR_CHUNK = 50_000

_SELECT_TAG_BY_ENTITY = """
    SELECT em.entity_id, MIN(lr.source_dataset)
    FROM aryx_entity_member em
    JOIN aryx_landed_record lr ON lr.id = em.landed_record_id AND lr.workspace_id = em.workspace_id
    WHERE em.workspace_id = %s
    GROUP BY em.entity_id
"""
_UPDATE_ATTRIBUTES = """
    UPDATE aryx_entity SET attributes = %s, updated_at = now()
    WHERE id = %s AND workspace_id = %s
"""
# Same tables and order as OracleGraphStore.clear(); chunked + committed per
# chunk so undo never has to hold a whole workspace's graph at once.
_GRAPH_TABLES = ("aryx_graph_provenance", "aryx_graph_edge", "aryx_graph_source", "aryx_graph_vertex")


def read_workspace(
    estore: EntityStore, workspace_id: int,
) -> tuple[dict[int, dict[str, Any]], dict[int, str], list[tuple[int, int]]]:
    """(entities, tag_of, contains) for plan_display_backfill."""
    entities = {int(eid): dict(attrs or {}) for eid, _ot, attrs in estore.list_entities()}
    with estore._pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_TAG_BY_ENTITY, (workspace_id,))
            tag_of = {int(eid): str(tag) for eid, tag in cur.fetchall() if tag}
    contains = [(int(s), int(t)) for s, t, name in estore.list_relationships()
                if name == RAW_EDGE_CONTAINS]
    return entities, tag_of, contains


def apply_updates(estore: EntityStore, workspace_id: int, plan: BackfillPlan) -> int:
    """Write planned attributes; one committed transaction per chunk."""
    rows = [(Json(attrs, dumps=_dumps), eid, workspace_id) for eid, attrs in plan.updates.items()]
    for i in range(0, len(rows), _CHUNK):
        with estore._pool.connection() as conn:  # commits on clean exit
            with conn.cursor() as cur:
                cur.executemany(_UPDATE_ATTRIBUTES, rows[i:i + _CHUNK])
        print(f"  updated {min(i + _CHUNK, len(rows))}/{len(rows)} entities", flush=True)
    return len(rows)


def delete_wrappers(estore: EntityStore, dsn: str, workspace_id: int, wrapper_ids: list[int]) -> int:
    """Drop wrapper entities' relationships, the entities (both chunked), then
    any ontology type left with no entities (no ghost types in the Ontology tab)."""
    type_of = {int(eid): ot for eid, ot, _attrs in estore.list_entities()}
    empty_types = types_fully_removed(type_of, wrapper_ids)
    for i in range(0, len(wrapper_ids), _CHUNK):
        with estore._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_impacted_relationships"),
                            {"workspace_id": workspace_id, "entity_ids": wrapper_ids[i:i + _CHUNK]})
    deleted = estore.delete_entities(wrapper_ids)
    ostore = OntologyStore(dsn, workspace_id)
    for name in empty_types:
        ostore.delete_type(name)
    print(f"  removed {len(empty_types)} now-empty ontology type(s): {empty_types}", flush=True)
    return deleted


def _preclear_oracle_graph(estore: EntityStore, workspace_id: int) -> None:
    """Delete the workspace's Oracle graph rows in committed chunks (undo-safe)."""
    with estore._pool.connection() as wrapped:
        conn = wrapped._conn  # raw oracledb connection: needs a commit per chunk
        cur = conn.cursor()
        for table in _GRAPH_TABLES:
            total = 0
            while True:
                cur.execute(f"DELETE FROM {table} WHERE workspace_id = :1 "
                            f"AND ROWNUM <= {_GRAPH_CLEAR_CHUNK}", (workspace_id,))
                n = cur.rowcount or 0
                conn.commit()
                total += n
                if n < _GRAPH_CLEAR_CHUNK:
                    break
            print(f"  pre-cleared {table}: {total}", flush=True)


def rebuild_graph(estore: EntityStore, dsn: str, settings: Any, workspace_id: int) -> dict:
    """Full rebuild -- raw SQL updates mark nothing dirty, so incremental would skip."""
    backend = settings.effective_graph_backend()
    if backend == "oci_graph":
        from aryx.graph.oracle_graph_store import OracleGraphStore
        _preclear_oracle_graph(estore, workspace_id)
        graph_inst = OracleGraphStore(settings.oci_adb_dsn, workspace_id)
    else:
        from aryx.graph import FalkorStore
        from aryx.naming import ws_graph
        graph_inst = FalkorStore(settings.graph_url, ws_graph(workspace_id))
    counts = project_graph(estore, graph_inst, type_ancestors=_build_type_ancestors(dsn),
                           workspace_id=workspace_id)
    print(f"  graph rebuilt: {counts}")
    return counts


def _print_plan(workspace_id: int, plan: BackfillPlan) -> None:
    """Human-readable dry-run summary with a few sample entities."""
    print(f"Workspace {workspace_id} display-name backfill plan:")
    print(f"  wrapper tags folded : {plan.wrapper_tags or 'none'}")
    print(f"  entities to update  : {len(plan.updates)}")
    print(f"  wrapper entities to delete: {len(plan.wrapper_entity_ids)}")
    for eid, attrs in list(plan.updates.items())[:8]:
        print(f"    e.g. entity {eid}: name={attrs.get('name')!r} "
              f"display_label={attrs.get('display_label')!r}")


def main() -> int:
    """CLI entry point: plan, then optionally apply + rebuild."""
    task_id = f"backfill-cpq-display-names-{uuid.uuid4()}"
    t0 = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Execute (default: dry-run only).")
    parser.add_argument("--keep-wrappers", action="store_true",
                        help="Update parents but do not delete the wrapper entities.")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="Skip planning; just retry the full graph rebuild.")
    args = parser.parse_args()

    settings = get_settings()
    dsn = settings.effective_dsn()
    wid = args.workspace_id
    estore = EntityStore(dsn, wid)
    try:
        if args.rebuild_only:
            counts = rebuild_graph(estore, dsn, settings, wid)
            raven_log("INFO", "P3", "backfill.display_names.completed rebuild-only finished",
                      context={"task_id": task_id, "workspace_id": wid, "final_status": "done",
                               "result": "ok", "reason_code": "REBUILD_ONLY", "stage": "backfill",
                               "duration_ms": int((time.monotonic() - t0) * 1000),
                               "projection_counts": dict(counts or {})})
            return 0

        plan = plan_display_backfill(*read_workspace(estore, wid))
        _print_plan(wid, plan)
        if not args.apply:
            print("\nDry run only -- pass --apply to execute.")
            return 0
        if not plan.updates and not plan.wrapper_entity_ids:
            print("\nNothing to change -- rebuilding the graph anyway (retry-safe).")
        updated = apply_updates(estore, wid, plan)
        deleted = 0 if args.keep_wrappers else delete_wrappers(estore, dsn, wid, plan.wrapper_entity_ids)
        counts = rebuild_graph(estore, dsn, settings, wid)
        raven_log("INFO", "P3", "backfill.display_names.completed backfill finished",
                  context={"task_id": task_id, "workspace_id": wid, "final_status": "done",
                           "result": "ok", "reason_code": "FOLD_AND_REBUILD_COMPLETE", "stage": "backfill",
                           "duration_ms": int((time.monotonic() - t0) * 1000),
                           "entities_updated": updated, "wrappers_deleted": deleted,
                           "wrapper_tags": plan.wrapper_tags, "projection_counts": dict(counts or {})})
        return 0
    finally:
        estore.close()


if __name__ == "__main__":
    sys.exit(main())
