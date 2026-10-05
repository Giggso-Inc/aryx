"""One-off backfill: rename raw-tag ontology types (e.g. "bm_prd_family") in
an already-ingested workspace into the PascalCase, source-prefixed shape
(e.g. "ApxNextConfigBmPrdFamily") every CPQ Ask-feature lookup expects.

Background: the raw-graph Confirm pipeline (cpq_ingestion/raw_graph/
resolve_relate.py) used to pass the raw XML tag straight through as
ontology_type, bypassing the naming convention the old CSV pipeline
produces via _stem_type(). That's fixed going forward at the source
(resolve_relate.py now derives ontology_type the same way), but workspaces
confirmed BEFORE that fix (workspace 1084/"CPQ Test V4" at minimum) still
have the broken type names sitting in aryx_entity / aryx_graph_vertex. This
script repairs those in place.

Approach:
  1. Find every ontology_type in the workspace that _catalog_prefix() can't
     parse a prefix from (the exact shape this bug produces).
  2. For each such type, recover the source filename stem(s) that produced
     it via aryx_landed_record.source_record_id (encoded as
     "{source_key}:{node_id}" by RawGraphConnector -- parsed back out with
     the existing parse_record_id() helper).
  3. If a type maps to exactly ONE source_key, compute the corrected name
     via the SAME _stem_type() call resolve_relate.py now uses, and rename
     every aryx_entity row of that type.
  4. If a type maps to MORE than one source_key (two files produced the
     same tag into the same workspace), skip it and report -- guessing
     wrong here is worse than leaving it broken.
  5. Re-run project_workspace_graph() so the curated graph store
     (FalkorDB/Oracle Graph) picks up the renamed types from Postgres.

Safety: dry-run by default (prints the rename plan, touches nothing).
Pass --apply to actually execute. Run manually, review the printed plan
first -- this is NOT wired into app startup or any automatic migration.

Usage:
    python scripts/backfill_raw_graph_ontology_type_naming.py --workspace-id 1084
    python scripts/backfill_raw_graph_ontology_type_naming.py --workspace-id 1084 --apply
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections import defaultdict

from aryx.config import get_settings
from aryx.cpq.catalog_naming import _catalog_prefix
from aryx.cpq_ingestion.raw_graph.resolve_adapter import parse_record_id
from aryx.pipeline.doc_discovery.doc_discovery_types import _stem_type
from aryx.pipeline.enrich.enrich import _build_type_ancestors
from aryx.project.project_full import project_graph
from aryx.raven_log import raven_log
from aryx.store.entity_store import EntityStore

_SELECT_TYPES_AND_SOURCE_KEYS = """
    SELECT DISTINCT e.ontology_type, lr.source_record_id
    FROM aryx_entity e
    JOIN aryx_entity_member em ON em.entity_id = e.id AND em.workspace_id = e.workspace_id
    JOIN aryx_landed_record lr ON lr.id = em.landed_record_id AND lr.workspace_id = e.workspace_id
    WHERE e.workspace_id = %s
"""

_UPDATE_ONTOLOGY_TYPE = """
    UPDATE aryx_entity SET ontology_type = %s
    WHERE workspace_id = %s AND ontology_type = %s
"""


def build_rename_plan(estore: EntityStore, workspace_id: int) -> tuple[dict[str, str], list[str]]:
    """Returns (old_type -> new_type renames, ambiguous types to skip)."""
    source_keys_by_type: dict[str, set[str]] = defaultdict(set)
    with estore._pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_TYPES_AND_SOURCE_KEYS, (workspace_id,))
            rows = cur.fetchall()

    for ontology_type, source_record_id in rows:
        if _catalog_prefix(ontology_type):
            continue  # already properly named -- not this bug
        try:
            source_key, _node_id = parse_record_id(source_record_id)
        except ValueError:
            continue  # not a raw-graph-sourced record; unrelated to this bug
        source_keys_by_type[ontology_type].add(source_key)

    renames: dict[str, str] = {}
    ambiguous: list[str] = []
    for old_type, keys in source_keys_by_type.items():
        if len(keys) != 1:
            ambiguous.append(old_type)
            continue
        (source_key,) = keys
        renames[old_type] = _stem_type(f"{source_key}_{old_type}")
    return renames, ambiguous


def apply_renames(estore: EntityStore, workspace_id: int, renames: dict[str, str]) -> None:
    # OracleConnectionWrapper commits on a clean __exit__ (and rolls back on
    # an exception) -- no explicit conn.commit() call exists on this wrapper;
    # calling one raises AttributeError, which (confirmed live) rolls the
    # whole batch back via that same exception path. Let the `with` block's
    # own exit handle the commit.
    with estore._pool.connection() as conn:
        with conn.cursor() as cur:
            for old_type, new_type in renames.items():
                cur.execute(_UPDATE_ONTOLOGY_TYPE, (new_type, workspace_id, old_type))


def main() -> int:
    task_id = f"backfill-ontology-type-naming-{uuid.uuid4()}"
    _t0 = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Execute the renames (default: dry-run only).")
    args = parser.parse_args()

    settings = get_settings()
    dsn = settings.effective_dsn()
    estore = EntityStore(dsn, args.workspace_id)

    renames, ambiguous = build_rename_plan(estore, args.workspace_id)

    if not renames and not ambiguous:
        print(f"Workspace {args.workspace_id}: no raw-tag ontology types found -- nothing to do.")
        return 0

    print(f"Workspace {args.workspace_id} rename plan:")
    for old_type, new_type in sorted(renames.items()):
        print(f"  {old_type!r} -> {new_type!r}")
    if ambiguous:
        print("\nSKIPPED (type maps to more than one source file -- needs manual review):")
        for old_type in sorted(ambiguous):
            print(f"  {old_type!r}")

    if not args.apply:
        print("\nDry run only -- pass --apply to execute these renames.")
        return 0

    if not renames:
        print("\nNothing to apply (every candidate type was ambiguous).")
        return 0

    apply_renames(estore, args.workspace_id, renames)
    print(f"\nRenamed {len(renames)} ontology type(s) in aryx_entity.")

    print("Rebuilding curated graph from corrected data (full rebuild, not "
          "incremental -- a raw SQL rename doesn't mark rows dirty, so "
          "project_workspace_graph()'s normal incremental-vs-full auto-pick "
          "would see 0 dirty entities and skip the graph store entirely; "
          "confirmed live against workspace 1084 before this fix -- "
          "aryx_entity renamed correctly, aryx_graph_vertex silently stayed "
          "stale)...")
    backend = settings.effective_graph_backend()
    type_ancestors = _build_type_ancestors(dsn)
    if backend == "oci_graph":
        from aryx.graph.oracle_graph_store import OracleGraphStore
        graph_inst = OracleGraphStore(settings.oci_adb_dsn, args.workspace_id)
    else:
        from aryx.graph import FalkorStore
        from aryx.naming import ws_graph
        graph_inst = FalkorStore(settings.graph_url, ws_graph(args.workspace_id))
    raven_log("DEBUG", "P4", "backfill.ontology_type.graph_backend_chosen backend selected for rebuild",
              context={"workspace_id": args.workspace_id, "selected_option": backend,
                       "available_options": ["oci_graph", "falkordb"],
                       "reason_code": "EFFECTIVE_GRAPH_BACKEND", "policy_version": "effective_graph_backend_v1",
                       "trace_id": task_id})
    counts = project_graph(estore, graph_inst, type_ancestors=type_ancestors, workspace_id=args.workspace_id)
    print(f"Done. {counts}")
    raven_log("INFO", "P3", "backfill.ontology_type.completed backfill finished",
              context={"task_id": task_id, "workspace_id": args.workspace_id, "final_status": "done",
                       "duration_ms": int((time.monotonic() - _t0) * 1000), "stage": "backfill",
                       "result": "ok", "reason_code": "RENAME_AND_REBUILD_COMPLETE",
                       "impact_scope": f"workspace {args.workspace_id} curated graph",
                       "renamed_types": len(renames), "skipped_ambiguous_types": len(ambiguous),
                       "projection_counts": dict(counts or {})})
    return 0


if __name__ == "__main__":
    sys.exit(main())
