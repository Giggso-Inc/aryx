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
  1. Find every ontology_type in the workspace that still LOOKS like a raw,
     unrenamed XML tag (snake_case, starts lowercase or "_" -- see
     _looks_like_unrenamed_raw_tag's docstring for why this is the right
     signal and _catalog_prefix() is NOT).
  2. For each such type, recover the source filename stem(s) that produced
     it via aryx_landed_record.source_record_id (encoded as
     "{source_key}:{node_id}" by RawGraphConnector -- parsed back out with
     the existing parse_record_id() helper).
  3. If a type maps to exactly ONE source_key, compute the corrected name
     via the SAME _stem_type(f"{source_key}_{tag}.csv") call
     resolve_relate.py now uses (the ".csv" matters -- see PR #435 review,
     High: without it, a source filename containing its own dot collapses
     every tag in that file onto one name), and rename every aryx_entity +
     aryx_ontology_type + aryx_schema_mapping row referencing that type.
  4. If a type maps to MORE than one source_key (two files produced the
     same tag into the same workspace), skip it and report -- guessing
     wrong here is worse than leaving it broken.
  5. Abort the WHOLE run (no partial apply) if the computed rename plan
     itself is unsafe: two old types mapping to the same new name, or a
     new name colliding with a type that already exists in this workspace
     under a different old name (PR #435 review, High -- the old script
     had no such check, so a dotted filename could silently merge
     distinct entity types under one name with no warning).
  6. Re-run project_graph() (a full rebuild, not the incremental auto-pick
     -- see the comment at its call site) so the curated graph store
     (FalkorDB/Oracle Graph) picks up the renamed types from Postgres.

Safety: dry-run by default (prints the rename plan, touches nothing).
Pass --apply to actually execute. Run manually, review the printed plan
first -- this is NOT wired into app startup or any automatic migration.

--apply always ends with a full graph rebuild, even on a run that finds
zero renames to make (PR #435 review, Medium: a renamed-but-not-yet-
rebuilt workspace -- e.g. a prior run's rebuild step failed after the
renames had already committed -- would otherwise never get retried,
since a re-run finds no more raw-tag types and used to exit early before
ever reaching the rebuild). Use --rebuild-only to skip rename planning
entirely and just retry the rebuild.

Usage:
    python scripts/backfill_raw_graph_ontology_type_naming.py --workspace-id 1084
    python scripts/backfill_raw_graph_ontology_type_naming.py --workspace-id 1084 --apply
    python scripts/backfill_raw_graph_ontology_type_naming.py --workspace-id 1084 --rebuild-only
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections import defaultdict

from aryx.config import get_settings
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

_SELECT_ALL_TYPES = "SELECT DISTINCT ontology_type FROM aryx_entity WHERE workspace_id = %s"

_UPDATE_ONTOLOGY_TYPE = """
    UPDATE aryx_entity SET ontology_type = %s
    WHERE workspace_id = %s AND ontology_type = %s
"""

# aryx_ontology_type (PR #435 review, Medium): the schema-diagram registry
# row for each type (upsert_ontology_type.sql) and the self-referential
# parent_type column (set_ontology_parent.sql) both key on the type's name,
# so a rename here would otherwise leave a ghost "empty type" with the old
# name in the diagram, and orphan any child type that pointed at it as a
# parent.
_RENAME_ONTOLOGY_TYPE_NAME = """
    UPDATE aryx_ontology_type SET name = %s
    WHERE workspace_id = %s AND name = %s
"""
_RENAME_ONTOLOGY_TYPE_PARENT = """
    UPDATE aryx_ontology_type SET parent_type = %s
    WHERE workspace_id = %s AND parent_type = %s
"""
# aryx_schema_mapping (PR #435 review, Medium): per-run provenance rows
# (insert_schema_mapping.sql) recording which source field mapped to which
# ontology_type/attribute -- has no workspace_id column of its own, scoped
# instead through run_id, so joined via aryx_landed_record the same way the
# rename-plan query above recovers source_key.
_RENAME_SCHEMA_MAPPING = """
    UPDATE aryx_schema_mapping SET ontology_type = %s
    WHERE ontology_type = %s
      AND run_id IN (SELECT run_id FROM aryx_landed_record WHERE workspace_id = %s)
"""


def _looks_like_unrenamed_raw_tag(ontology_type: str) -> bool:
    """True for a type that's still the literal raw XML tag (e.g.
    "bm_prd_family", "_children") -- never touched by either pipeline's
    naming.

    NOT the same check as "_catalog_prefix(type) == ''" (a live bug found
    while re-running this script against an already-backfilled workspace,
    PR #435 follow-up): a tag with no "bm_" marker (e.g. "name", "_children",
    "description") NEVER gets a parseable _catalog_prefix even once
    correctly renamed -- that's true of the OLD CSV pipeline too, not a sign
    the type still needs fixing. Using that as the "needs fixing" signal
    would re-run the rename on an already-correct type on every subsequent
    invocation, double-prefixing it (confirmed live: "Svx Video Remote
    Speaker MicrophoneChildren" -> "...MicrophoneSvx Video Remote Speaker
    Microphonechildren").

    The actually-reliable signal: _stem_type() always title-cases its first
    word, so every type either pipeline ever produces starts with an
    uppercase letter (or a digit, if the source filename itself starts with
    one). A still-raw BigMachines/CPQ XML tag is snake_case and starts with
    a lowercase letter or an underscore (container tags like "_children").
    """
    if not ontology_type:
        return False
    first = ontology_type[0]
    return first == "_" or first.islower()


def build_rename_plan(
    estore: EntityStore, workspace_id: int,
) -> tuple[dict[str, str], list[str], list[str]]:
    """Returns (old_type -> new_type renames, ambiguous types to skip,
    collisions that abort the whole run)."""
    source_keys_by_type: dict[str, set[str]] = defaultdict(set)
    with estore._pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_TYPES_AND_SOURCE_KEYS, (workspace_id,))
            rows = cur.fetchall()
            cur.execute(_SELECT_ALL_TYPES, (workspace_id,))
            all_existing_types = {r[0] for r in cur.fetchall()}

    for ontology_type, source_record_id in rows:
        if not _looks_like_unrenamed_raw_tag(ontology_type):
            continue  # already renamed (or never needed renaming) -- not this bug
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
        # The ".csv" suffix matters -- see the matching comment at
        # resolve_relate.py's own _stem_type() call site (PR #435 review,
        # High). _stem_type does Path(filename).stem, which strips
        # everything after the LAST "." -- a source filename with its own
        # dot (a version number, a date) would otherwise eat part of the
        # tag and collapse every tag in that file onto one name.
        renames[old_type] = _stem_type(f"{source_key}_{old_type}.csv")

    # Collision check (PR #435 review, High): abort the whole run rather
    # than apply a plan that would silently merge distinct entity types
    # under one name. Two kinds of collision:
    #  1. Two different old types computed the SAME new name (e.g. a
    #     dotted source key that still collapses two tags together even
    #     with the .csv fix, or a genuine _stem_type singularization
    #     collision).
    #  2. A computed new name already exists in the workspace under a
    #     DIFFERENT old type that isn't part of this rename at all.
    new_name_to_old_types: dict[str, list[str]] = defaultdict(list)
    for old_type, new_type in renames.items():
        new_name_to_old_types[new_type].append(old_type)
    collisions: list[str] = []
    for new_type, old_types in new_name_to_old_types.items():
        if len(old_types) > 1:
            collisions.append(
                f"{new_type!r} would be the new name for {len(old_types)} distinct "
                f"old types: {sorted(old_types)!r}"
            )
    pre_existing_other_types = all_existing_types - set(renames)
    for new_type in new_name_to_old_types:
        if new_type in pre_existing_other_types:
            collisions.append(
                f"{new_type!r} already exists in this workspace under a type not "
                f"being renamed"
            )

    return renames, ambiguous, collisions


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
                cur.execute(_RENAME_ONTOLOGY_TYPE_NAME, (new_type, workspace_id, old_type))
                cur.execute(_RENAME_ONTOLOGY_TYPE_PARENT, (new_type, workspace_id, old_type))
                cur.execute(_RENAME_SCHEMA_MAPPING, (new_type, old_type, workspace_id))


def rebuild_graph(estore: EntityStore, dsn: str, settings, workspace_id: int, task_id: str) -> dict:
    """Full (not incremental) graph rebuild -- see the long comment below for why
    incremental is wrong here. Factored out so --rebuild-only and the normal
    --apply path share one implementation (PR #435 review, Medium: a failed
    rebuild used to have no retry path once the renames that triggered it were
    already committed)."""
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
        graph_inst = OracleGraphStore(settings.oci_adb_dsn, workspace_id)
    else:
        from aryx.graph import FalkorStore
        from aryx.naming import ws_graph
        graph_inst = FalkorStore(settings.graph_url, ws_graph(workspace_id))
    raven_log("DEBUG", "P4", "backfill.ontology_type.graph_backend_chosen backend selected for rebuild",
              context={"workspace_id": workspace_id, "selected_option": backend,
                       "available_options": ["oci_graph", "falkordb"],
                       "reason_code": "EFFECTIVE_GRAPH_BACKEND", "policy_version": "effective_graph_backend_v1",
                       "trace_id": task_id})
    _t0 = time.monotonic()
    counts = project_graph(estore, graph_inst, type_ancestors=type_ancestors, workspace_id=workspace_id)
    print(f"Done. {counts}")
    raven_log("INFO", "P4", "backfill.ontology_type.graph_rebuilt full rebuild finished",
              context={"task_id": task_id, "workspace_id": workspace_id, "final_status": "done",
                       "duration_ms": int((time.monotonic() - _t0) * 1000), "stage": "graph_rebuild",
                       "result": "ok", "reason_code": "FULL_REBUILD_COMPLETE",
                       "impact_scope": f"workspace {workspace_id} curated graph"})
    return counts


def main() -> int:
    task_id = f"backfill-ontology-type-naming-{uuid.uuid4()}"
    _t0 = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Execute the renames (default: dry-run only).")
    parser.add_argument("--rebuild-only", action="store_true",
                         help="Skip rename planning; just retry the full graph rebuild "
                              "(e.g. after a prior --apply's rebuild step failed).")
    args = parser.parse_args()

    settings = get_settings()
    dsn = settings.effective_dsn()
    estore = EntityStore(dsn, args.workspace_id)

    if args.rebuild_only:
        counts = rebuild_graph(estore, dsn, settings, args.workspace_id, task_id)
        raven_log("INFO", "P3", "backfill.ontology_type.completed rebuild-only finished",
                  context={"task_id": task_id, "workspace_id": args.workspace_id, "final_status": "done",
                           "duration_ms": int((time.monotonic() - _t0) * 1000), "stage": "backfill",
                           "result": "ok", "reason_code": "REBUILD_ONLY",
                           "impact_scope": f"workspace {args.workspace_id} curated graph",
                           "renamed_types": 0, "skipped_ambiguous_types": 0,
                           "projection_counts": dict(counts or {})})
        return 0

    renames, ambiguous, collisions = build_rename_plan(estore, args.workspace_id)

    if collisions:
        print(f"ABORTED -- the rename plan for workspace {args.workspace_id} is unsafe, nothing was touched:")
        for reason in collisions:
            print(f"  {reason}")
        print("\nThis needs manual review -- a rename here would silently merge "
              "distinct entity types under one name.")
        raven_log("WARN", "P2", "backfill.ontology_type.aborted_unsafe_plan rename plan rejected",
                  context={"task_id": task_id, "workspace_id": args.workspace_id, "final_status": "aborted",
                           "duration_ms": int((time.monotonic() - _t0) * 1000), "stage": "backfill",
                           "result": "error", "reason_code": "UNSAFE_RENAME_PLAN",
                           "impact_scope": f"workspace {args.workspace_id}: no changes made",
                           "collision_count": len(collisions)})
        return 1

    if not renames and not ambiguous:
        print(f"Workspace {args.workspace_id}: no raw-tag ontology types found -- nothing to rename.")
        if not args.apply:
            return 0
        # Still rebuild on --apply even with nothing to rename (see
        # rebuild_graph's docstring) -- a prior run may have applied the
        # renames already and failed only at the rebuild step.
        counts = rebuild_graph(estore, dsn, settings, args.workspace_id, task_id)
        raven_log("INFO", "P3", "backfill.ontology_type.completed nothing to rename, rebuilt anyway",
                  context={"task_id": task_id, "workspace_id": args.workspace_id, "final_status": "done",
                           "duration_ms": int((time.monotonic() - _t0) * 1000), "stage": "backfill",
                           "result": "ok", "reason_code": "NOTHING_TO_RENAME_REBUILT",
                           "impact_scope": f"workspace {args.workspace_id} curated graph",
                           "renamed_types": 0, "skipped_ambiguous_types": 0,
                           "projection_counts": dict(counts or {})})
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

    if renames:
        apply_renames(estore, args.workspace_id, renames)
        print(f"\nRenamed {len(renames)} ontology type(s) across aryx_entity, "
              f"aryx_ontology_type, and aryx_schema_mapping.")
    else:
        print("\nNothing to rename (every candidate type was ambiguous) -- rebuilding anyway.")

    counts = rebuild_graph(estore, dsn, settings, args.workspace_id, task_id)
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
