"""Pass 2: resolve every raw-graph tag into curated entities, relate them via
containment, and project the result into the curated graph.

Separate from ``pipeline.py``'s ``project_raw_graph_and_flatten`` (Pass 1,
the read-time raw-graph write) because the two run at different times against
different call sites -- Pass 1 runs during discovery/read for every upload
with the raw graph enabled; this runs only once ``ingest_confirmed()``
decides a source file's plans are cpq_ingestion-active (see
``routing.partition_cpq_ingestion_plans``). Its caller recomputes the same
projection fresh from the original XML bytes (``project_xml_to_raw_graph``
is pure and deterministic, so this reproduces exactly what Pass 1 wrote,
without a round-trip read from FalkorDB/Oracle Graph) and hands it in here
to push through resolve/relate directly, tag by tag, landing the result in
the curated graph the "Graph" tab already reads (``ws_graph(workspace_id)``).
Pass 1's stored raw graph itself is not read by this or anything else --
it remains a write-only provenance artifact.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from collections import defaultdict

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.cpq_ingestion.raw_graph.containment_relate import translate_containment_edges
from aryx.cpq_ingestion.raw_graph.match_key_inference import infer_match_keys_for_tag
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.cpq_ingestion.raw_graph.store import with_query_tables
from aryx.cpq_ingestion.raw_graph.resolve_adapter import (
    SOURCE_SYSTEM,
    RawGraphConnector,
    group_nodes_by_tag,
    parse_record_id,
)
from aryx.cpq_ingestion.raw_graph.structural_leaf import fold_structural_leaf_tags
from aryx.cpq_ingestion.raw_graph.xml_projector import iter_raw_graph, project_xml_to_raw_graph
from aryx.pipeline.doc_discovery.doc_discovery_types import _stem_type
from aryx.pipeline.orchestrate import PipelineCancelled, Progress, project_workspace_graph, run_pipeline
from aryx.store.entity_store import EntityStore

from aryx.raven_log import current_run_id, raven_log

logger = logging.getLogger(__name__)


def _delete_orphaned_entities(
    estore: EntityStore, node_id_to_entity_id: dict[int, int],
    *, log_id: str | None, source_key: str,
) -> None:
    """Roll back entities already created by earlier tags in THIS attempt
    when a cancel lands mid-loop (PR #429 review M1).

    Relationships are only saved once, after every tag finishes (see
    translate_containment_edges/save_relationships below) -- so a cancel
    here means these entities have no relationships yet and would otherwise
    sit in the DB as orphans, surfacing as isolated nodes once
    project_workspace_graph next rebuilds the graph from everything in the
    DB. Deleting them now means a cancelled attempt leaves nothing behind:
    the next confirm (re-confirming this same file, or confirming anything
    else in the workspace) starts from a clean slate for this source file
    instead of adding to leftover orphans on top of whatever a retry
    creates.

    Stale note corrected (PR review round 7, Low): this used to say member
    rows were left as orphans, matching EntityStore.delete_entity()/
    delete_entities_by_type()'s then-limitation -- that limitation was
    closed for all three delete methods (§5, 2026-10-04): delete_entities()
    (which this function actually calls) now deletes each chunk's
    aryx_entity_member rows before the entity rows themselves, same
    transaction, same FK-ordering reason as delete_entity()'s own
    docstring. Nothing is left orphaned here any more.

    One round-trip, not one per entity (PR #429 review N1): a cancel after
    many tags on a large file (the 5.85M-node upload this PR's cancellation
    support targets) could otherwise mean many individual DELETEs just to
    clean up -- undermining the "cancel should be prompt" goal this PR
    exists for. EntityStore.delete_entities() takes the full id list in one
    DELETE (same array-param pattern as delete_impacted_entities.sql).

    Best-effort: a deletion failure is logged and skipped rather than
    raised, so a DB hiccup while cleaning up after a cancel never masks the
    cancellation itself.
    """
    if not node_id_to_entity_id:
        return
    entity_ids = sorted(set(node_id_to_entity_id.values()))
    try:
        deleted = estore.delete_entities(entity_ids)
    except Exception:  # noqa: BLE001 -- cleanup is best-effort, never mask the cancel
        logger.warning(
            "raw_graph resolve_and_relate did=%s source_key=%s: failed to delete "
            "%d orphaned entity(ies) after cancel", log_id, source_key, len(entity_ids), exc_info=True,
        )
        deleted = 0
    logger.warning(
        "raw_graph resolve_and_relate did=%s source_key=%s: cancelled -- deleted %d/%d "
        "orphaned entity(ies) from already-resolved tags",
        log_id, source_key, deleted, len(entity_ids),
    )
    raven_log("WARN", "P3", "ingest.raw_graph.cancel_cleanup orphaned entities deleted after cancel",
              error_code="ARYX_ING_CANCELLED",
              context={"log_id": log_id, "source_key": source_key, "entities_attempted": len(entity_ids),
                       "entities_deleted": deleted, "result": "cancelled",
                       "exit_condition": "cancelled"})


def resolve_and_relate_raw_graph(
    projection: RawGraphProjection | None = None,
    *,
    xml_bytes: bytes | None = None,
    workspace_id: int,
    source_key: str,
    dsn: str,
    graph_url: str,
    broker: Broker,
    context: str = "",
    log_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_progress: Progress | None = None,
) -> dict[str, Any]:
    """Resolve every raw-graph tag into curated entities, relate via
    containment, and project the result into the curated graph.

    Exactly one of ``projection`` / ``xml_bytes`` must be given.
    ``xml_bytes`` (§3b, 2026-10-04) opts into the streaming path when
    ``ARYX_CPQ_STREAMING_PROJECTION_ENABLED`` is on: ``by_tag`` is built
    incrementally from ``xml_projector.iter_raw_graph()`` instead of a
    fully-materialized ``RawGraphProjection``. Default-off and falls back
    to the eager ``project_xml_to_raw_graph()`` path when the flag is off
    OR when ``ARYX_CSV_BML_ENABLED``'s query-table enrichment is on
    (``with_query_tables()`` has no streaming equivalent -- correctness
    over memory savings when both are enabled).

    Memory benefit, measured (PR review N3, 2026-10-04 -- corrects this
    docstring's earlier, unmeasured framing): the large DOM-memory problem
    this module was originally built to fix (a full in-memory element
    tree) was already solved by ``project_xml_to_raw_graph`` itself
    switching to ``iterparse`` + ``elem.clear()``, well before this
    streaming path existed -- it does NOT hold a full tree either, and
    this path's by_tag/edges dicts retain every node/edge object either
    way (the node objects and their property dicts are the SAME objects
    either path produces, not copies). The only memory this path actually
    removes is ``RawGraphProjection``'s own ``nodes``/``edges`` list
    overhead -- measured directly: 160.7 MB (eager) vs. 157.5 MB
    (streaming) for a 400,000-element flat document, a 2.0% difference,
    ~8.1 bytes/node (matches the ~8-byte pointer-list prediction this
    review made before the measurement existed). Real, free (no
    correctness cost once N2 below is fixed), and worth keeping opt-in --
    but it is a modest, not a dramatic, saving, and should not be confused
    with the original DOM-tree fix.

    Not yet verified against a real large file end to end for full-pipeline
    (not just parser-level) correctness at production scale -- see the
    planning doc's §3b implementation-plan note for what IS verified
    (live-tested at 3,000-record scale, full pipeline, byte-identical
    output) -- ships opt-in, not default-on, until the real ~440k-record
    file is tried.

    One resolve-only run per distinct XML tag: a ``RawGraphConnector`` for
    that tag's nodes, with ``ontology_type``/``match_keys`` from
    ``infer_match_keys_for_tag``, run through ``run_pipeline`` with
    ``relate=False, skip_graph=True`` — no FK-guessing stage runs (_relate,
    schema_fk, cooccurrence, relate_isolated, dimension_link all exist to
    guess structure a CSV/document source doesn't carry); the true
    parent/child structure is already known from the XML itself, applied
    directly afterward via ``translate_containment_edges``. A single
    ``project_workspace_graph`` call at the end performs the one graph
    projection this whole file needs — the same function ``run_pipeline``'s
    own project stage now delegates to (see ``orchestrate.py``).

    on_progress: optional callback reporting progress across the whole
    per-tag loop, 0-100 -- previously this function reported nothing at
    all, so the caller's job-status row sat at a single static "Resolving
    {source_filename}..." / pct=0 for this file's *entire* duration (which
    can be 30+ minutes for a single large tag), making a healthy run
    indistinguishable from a stalled one. Each tag's own run_pipeline()
    call already supports on_progress (Discover/Resolve/Relate/Project
    stages, 0-100 internally) -- this wraps that per-tag signal, scaled by
    which tag (of how many) is in flight, into one combined 0-100 signal
    for the whole file: ``((tag_index - 1) * 100 + inner_pct) /
    total_tags``. Callers that want a sub-progress breakdown per tag get
    one for free via the forwarded ``stage``/``detail`` strings (prefixed
    with ``"{tag_index}/{total_tags}"``).

    should_stop: optional cancellation poll, checked once per tag (before
    that tag's run_pipeline call starts) and once more before the final
    project_workspace_graph call -- this confirm path previously had zero
    cancellation support at all, unlike the Read-stage raw-graph write
    (PR #425). A multi-tag/multi-file XML confirm's cost is spread across
    many per-tag run_pipeline calls, so checking between them meaningfully
    shrinks the cancel-to-stop window. Also forwarded into each
    run_pipeline call so an already-running tag's own discover/resolve
    stages observe it too (run_pipeline already supports should_stop).
    Does NOT make project_workspace_graph's own write interruptible
    mid-write -- that function is shared by every ingestion path in the
    system, not just cpq_ingestion XML, and is a separate, larger gap left
    out of scope here (same as it already is for every other caller).

    Trade-off (PR #429 review): a cancel that lands after the last tag's
    entities/relationships are already saved but before this final
    project_workspace_graph call leaves the curated GRAPH stale relative to
    the DB -- entities/relationships exist, the graph doesn't reflect them
    yet. Accepted: project_workspace_graph rebuilds the whole workspace
    graph from the DB every time it runs, so the next real confirm (for
    this file or any other) in the workspace repairs it; nothing is lost,
    only delayed.

    Not resumable (PR #429 review M1, after an earlier, wrong claim in this
    docstring that re-running resolve would merge onto prior entities --
    verified false): unlike the generic CSV plan loop in ingest_confirmed()
    (which tracks completed_plans and skips already-done files on a
    restart), a cancelled cpq XML source file is never marked complete, so
    re-confirming it redoes every tag from scratch. resolve_run()/resolve()
    only cluster the records passed to THAT call against each other -- they
    have no knowledge of entities a previous run already created, and
    relate=False here means the FK/relate stage that could otherwise catch
    some duplicates never runs either. EntityStore.save()'s own
    insert_entity.sql is a plain INSERT (no ON CONFLICT, no existing-entity
    lookup), confirmed by reading it -- every resolve_run() call for the
    same data creates brand new entity rows, for every tag, regardless of
    whether it has a real match key, an LLM-guessed one, or none at all.

    Mitigated, not eliminated (PR #429 review M1, second round -- the first
    round only caught the should_stop() check at the top of the loop; it
    missed that run_pipeline() itself can ALSO raise PipelineCancelled from
    inside a tag, via orchestrate.py's own "relate" checkpoint, which fires
    unconditionally right after resolve_cluster -- the expensive embedding/
    entity-resolution stage and the bulk of a tag's cost -- regardless of
    relate=False here. That is the MOST likely real-world cancellation
    point, not the pre-tag check, so an except PipelineCancelled now wraps
    the whole tag loop, catching both paths):

    When caught, _delete_orphaned_entities (below) deletes every entity
    already created by tags that fully completed BEFORE the one in flight
    when the cancel landed -- relationships are only saved once, after
    every tag finishes, so those entities never had any yet and would
    otherwise sit as permanent orphans once project_workspace_graph next
    rebuilds the graph from everything in the DB.

    PR #429 review N1 (round 2) closed what was the main remaining gap: a
    cancel raised from INSIDE run_pipeline() -- the common case, since the
    "relate" checkpoint fires right after resolve_cluster, i.e. AFTER that
    tag's own entities are already saved -- used to leave that WHOLE
    in-flight tag's entities behind uncleaned (node_id_to_entity_id is only
    populated after run_pipeline returns successfully, so a raise meant
    this function never learned that tag's run_id). orchestrate.py's
    _check_cancelled now attaches run_id onto the PipelineCancelled it
    raises; the except block here looks those entities up via the same
    entity_ids_by_run() the successful path already uses and folds them
    into the same cleanup call. So a mid-loop cancel -- whichever of the
    two paths triggers it -- now cleans up every tag that reached
    resolve_cluster, in-flight one included, not just the ones that fully
    finished before it.

    Does NOT prevent duplication across separate confirm attempts that each
    ran to completion (re-confirming an already-finished file, or a cancel
    that lands after the last tag but before the final project_workspace_
    graph call -- see the trade-off note above, where entities+relationships
    are already correctly saved and nothing needs cleanup). True
    resumability (skipping already-resolved tags, mirroring the generic CSV
    path's completed_plans) is a separate, larger feature and still out of
    scope for this PR.
    """
    if (projection is None) == (xml_bytes is None):
        raise ValueError("resolve_and_relate_raw_graph: exactly one of "
                         "projection/xml_bytes must be given")

    _t0 = time.monotonic()
    total_entities = 0
    relationships: list[Any] = []
    graph_counts: dict[str, int] = {}
    settings = get_settings()

    # Lazy import (matches with_query_tables' own precedent in store.py)
    # to avoid an import cycle between csv_bml_ingestion and cpq_ingestion.
    from aryx.csv_bml_ingestion.config import csv_bml_enabled  # noqa: PLC0415

    # §3b: stream straight from bytes only when opted in AND the BML
    # query-table enrichment (which needs a complete RawGraphProjection,
    # no streaming equivalent) isn't also on -- see the docstring.
    use_streaming = (
        xml_bytes is not None
        and settings.cpq_streaming_projection_enabled
        and not csv_bml_enabled()
    )

    # PR review round 5 (Raven logging, N4): this routing decision had no
    # dedicated raven_log entry at all -- flagged by the decision-map tool
    # and previously just baselined rather than fixed. Logged once per
    # call so it's possible to tell, after the fact, which path a given
    # source file actually took.
    raven_log("DEBUG", "P4", "ingest.raw_graph.path_chosen streaming vs. eager projection path",
              context={"log_id": log_id, "source_key": source_key,
                       "selected_option": "streaming" if use_streaming else "eager",
                       "available_options": ["streaming", "eager"],
                       "reason_code": "CPQ_STREAMING_PROJECTION_ENABLED" if use_streaming
                                      else "STREAMING_DISABLED_OR_BML_ENABLED",
                       "policy_version": "cpq_streaming_route_v1",
                       "trace_id": current_run_id()})
    if use_streaming:
        by_tag: dict[str, list[RawNode]] = defaultdict(list)
        edges: list[RawEdge] = []
        for node, edge in iter_raw_graph(xml_bytes, should_stop=should_stop):
            by_tag[node.tag].append(node)
            if edge is not None:
                edges.append(edge)
        # PR review N2 (2026-10-04): iter_raw_graph yields in finish
        # (post-)order -- relative order among SIBLINGS matches the eager
        # path (see its docstring), but a tag that recurs at more than one
        # nesting depth in the SAME document (e.g. a self-nesting catalog/
        # category tree) comes out child-before-parent in post-order,
        # while the eager path's id-ordered projection.nodes always has
        # the parent (lower id, started first) before the child (higher
        # id, started later). The equivalence test this shipped with used
        # a flat file with no such nesting, so it never caught this.
        # match_key_inference/resolve's merge tie-breaks and entity-id
        # assignment are order-sensitive per xml_projector's own docstring
        # -- sorting each tag's list back into id order here restores the
        # eager path's exact per-tag ordering (O(n log n) over ints,
        # negligible next to the resolve pass itself) before anything
        # downstream can observe the difference.
        by_tag = {tag: sorted(nodes, key=lambda n: n.id) for tag, nodes in by_tag.items()}
        if not by_tag:
            logger.info(
                "raw_graph resolve_and_relate did=%s source_key=%s: no nodes to resolve",
                log_id, source_key,
            )
            raven_log("DEBUG", "P4", "ingest.raw_graph.resolve nothing to resolve",
                      context={"log_id": log_id, "source_key": source_key, "decision": "early_return",
                               "reason_code": "NO_NODES"})
            return {"tags": 0, "entities": 0, "relationships": 0}
    else:
        if projection is None:
            projection = project_xml_to_raw_graph(xml_bytes, should_stop=should_stop)
        if not projection.nodes:
            logger.info(
                "raw_graph resolve_and_relate did=%s source_key=%s: no nodes to resolve",
                log_id, source_key,
            )
            raven_log("DEBUG", "P4", "ingest.raw_graph.resolve nothing to resolve",
                      context={"log_id": log_id, "source_key": source_key, "decision": "early_return",
                               "reason_code": "NO_NODES"})
            return {"tags": 0, "entities": 0, "relationships": 0}
        # Opt-in (ARYX_CSV_BML_ENABLED): the curated graph is what a CSV upload searches for the BML query,
        # so the query lists must be on the entities that resolve/relate builds it from.
        projection = with_query_tables(projection)
        by_tag = group_nodes_by_tag(projection)
        edges = projection.edges

    # PR review N1: opt-out for a new behavior-changing fix, even one
    # believed safe (every existing per-caller test keeps passing with the
    # default True).
    if settings.cpq_structural_leaf_fold_enabled:
        by_tag = fold_structural_leaf_tags(
            edges, by_tag, log_id=log_id, source_key=source_key,
        )
    total_tags = len(by_tag)
    node_id_to_entity_id: dict[int, int] = {}
    estore = EntityStore(dsn, workspace_id)
    try:
        try:
            for tag_index, (tag, nodes) in enumerate(by_tag.items(), start=1):
                if should_stop is not None and should_stop():
                    raise PipelineCancelled(
                        f"job cancelled before tag={tag} source_key={source_key}",
                    )
                inferred = infer_match_keys_for_tag(tag, nodes, context, log_id=log_id)
                connector = RawGraphConnector(nodes, tag=tag, source_key=source_key)

                def _tag_progress(stage: str, pct: int, detail: str,
                                   _idx: int = tag_index, _total: int = total_tags,
                                   _tag: str = tag) -> None:
                    if on_progress is None:
                        return
                    overall_pct = int(((_idx - 1) * 100 + pct) / _total)
                    on_progress(f"{_idx}/{_total} · {stage}", overall_pct,
                                f"[{_tag}] {detail}")

                # run_pipeline's own should_stop checks (orchestrate.py's
                # _check_cancelled) can ALSO raise PipelineCancelled from
                # inside this call -- its "relate" checkpoint fires
                # unconditionally right after the resolve_cluster stage,
                # the expensive embedding/entity-resolution part and the
                # bulk of a tag's cost, regardless of relate=False here.
                # That is the MOST likely real-world cancellation point
                # (PR #429 review M1), not the should_stop() check above,
                # so it must be caught by the same except below, not left
                # to propagate uncleaned.
                # §1 Tier 2 (2026-10-04): infer_match_keys_for_tag's "default"
                # source means it found a real, observed property but wasn't
                # confident enough to call it a match key by name (the
                # heuristic/LLM both passed) -- this is exactly the shape of
                # cpq_ingestion's generic "text" fallback key, whose values
                # can still turn out to be fully unique (confirmed live:
                # 439,946/439,946 unique on a real run). Forcing exact mode
                # here skips paying for _key_selectivity()'s sampling pass
                # just to discover the same thing non-deterministically.
                # Naming parity with the old CSV pipeline (Ask-feature review,
                # 2026-10-05): infer_match_keys_for_tag's own ontology_type is
                # the raw XML tag (e.g. "bm_prd_family"), but every CPQ
                # Ask-feature lookup keyed off a workspace's ingested catalogs
                # (list_ingested_families, product-hint resolution, catalog
                # scoping, product-config menus, rule export, model-path
                # resolution -- see cpq/catalog_naming.py's _catalog_prefix)
                # expects the OLD _xml_to_csvs()-path convention instead:
                # PascalCase, source-prefixed, e.g. "ApxNextConfigBmPrdFamily".
                # That shape falls out of running "{stem}_{tag}.csv" through
                # _stem_type() (doc_discovery_types.py) on the old path --
                # reusing the exact same function here (not reimplementing the
                # title-casing logic) guarantees byte-identical output for the
                # same (source file, XML tag) pair, which is what lets every
                # existing _catalog_prefix() consumer keep working unchanged.
                # Confirmed live: without this, a raw-graph-ingested workspace
                # (e.g. 1084/"SVX") has zero ontology types _catalog_prefix can
                # parse a prefix from, so the Ask feature believes nothing was
                # ever ingested.
                #
                # The ".csv" suffix below is NOT cosmetic (PR #435 review,
                # High): _stem_type calls Path(filename).stem, which strips
                # everything after the LAST "." in the string. The old
                # pipeline's input was always "{stem}_{tag}.csv", so .stem
                # only ever ate the ".csv" extension. Passing
                # f"{source_key}_{tag}" with no extension means a source
                # filename containing its own dot (a version number like
                # "APX Next 2.0 Config", a date like "export_2026.10.05")
                # gets stripped at ITS last dot instead -- eating part or all
                # of the tag and collapsing every tag in that file onto one
                # ontology_type. Verified live: _stem_type("export_2026.10.05
                # _bm_prd_family") == "Export2026.10" (wrong) vs.
                # _stem_type("export_2026.10.05_bm_prd_family.csv") ==
                # "Export2026.10.05BmPrdFamily" (matches the old pipeline).
                summary = run_pipeline(
                    connector=connector, dsn=dsn, system=SOURCE_SYSTEM, dataset=tag,
                    ontology_type=_stem_type(f"{source_key}_{tag}.csv"), match_keys=inferred["match_keys"],
                    graph_url=graph_url, broker=broker, workspace_id=workspace_id,
                    relate=False, skip_graph=True, should_stop=should_stop,
                    on_progress=_tag_progress,
                    force_exact=(settings.cpq_force_exact_enabled
                                and inferred.get("source") == "default"),
                )
                total_entities += summary["entities"]
                for record_id, entity_id in estore.entity_ids_by_run(summary["run_id"]).items():
                    _, node_id = parse_record_id(record_id)
                    node_id_to_entity_id[node_id] = entity_id
                logger.info(
                    "raw_graph resolve_and_relate did=%s source_key=%s tag=%s run_id=%s entities=%d",
                    log_id, source_key, tag, summary["run_id"], summary["entities"],
                )
                raven_log("DEBUG", "P4", "ingest.raw_graph.resolve tag resolved",
                          context={"log_id": log_id, "source_key": source_key, "tag": tag, "nodes": len(nodes),
                                   "run_id": summary["run_id"], "entities": summary["entities"],
                                   "match_keys": inferred["match_keys"]})
        except PipelineCancelled as exc:
            # Covers both paths above: the explicit should_stop() check at
            # the top of the loop, and a PipelineCancelled raised from
            # inside run_pipeline() for the tag currently in flight.
            #
            # PR #429 review N1 (round 2): run_pipeline's own
            # _check_cancelled now attaches the in-flight tag's run_id onto
            # the exception it raises -- the "relate" checkpoint fires right
            # after resolve_cluster, i.e. AFTER that tag's entities are
            # already saved, so without this they'd be undercounted orphans
            # every time (the common case, not a small one). When present,
            # look those entities up the same way the tag loop itself does
            # on success (estore.entity_ids_by_run) and fold them into the
            # cleanup set alongside the already-completed tags' entities.
            orphan_ids = dict(node_id_to_entity_id)
            if exc.run_id is not None:
                try:
                    in_flight = estore.entity_ids_by_run(exc.run_id)
                except Exception:  # noqa: BLE001 -- best-effort, see _delete_orphaned_entities
                    logger.warning(
                        "raw_graph resolve_and_relate did=%s source_key=%s: failed to look up "
                        "in-flight run_id=%s entities for cleanup", log_id, source_key, exc.run_id,
                        exc_info=True,
                    )
                else:
                    for record_id, entity_id in in_flight.items():
                        _, node_id = parse_record_id(record_id)
                        orphan_ids[node_id] = entity_id
            _delete_orphaned_entities(estore, orphan_ids, log_id=log_id, source_key=source_key)
            raise

        relationships = translate_containment_edges(
            edges, node_id_to_entity_id, log_id=log_id,
        )
        if relationships:
            # PR review (2026-10-04): previously no on_progress here at all --
            # see save_relationships' own docstring for why that's unsafe
            # now that a heartbeat-sweep watchdog exists.
            estore.save_relationships(relationships, on_progress=on_progress)

        if should_stop is not None and should_stop():
            raise PipelineCancelled(
                f"job cancelled before final graph projection source_key={source_key}",
            )
        # Same reasoning: project_workspace_graph() already supports
        # on_progress (project_auto's own per-batch checkpoints), it just
        # wasn't being passed from this call site.
        graph_counts = project_workspace_graph(dsn, graph_url, workspace_id, estore,
                                               on_progress=on_progress)
    finally:
        estore.close()

    result = {"tags": len(by_tag), "entities": total_entities,
              "relationships": len(relationships), **graph_counts}
    logger.info("raw_graph resolve_and_relate complete did=%s source_key=%s %s",
                log_id, source_key, result)
    # PR review round 5 (Raven logging, N4): this was previously missing
    # every field the decision-map tool requires for an [Outcome] log
    # (task_id/final_status/duration_ms/stage/result/impact_scope) --
    # baselined rather than fixed in an earlier round. Added here instead.
    raven_log("INFO", "P4", "ingest.raw_graph.resolved raw graph resolved into curated graph",
              context={"log_id": log_id, "source_key": source_key, "workspace_id": workspace_id,
                       "tags": len(by_tag), "entities": total_entities, "relationships": len(relationships),
                       "task_id": log_id, "final_status": "complete", "stage": "resolve_and_relate",
                       "result": "ok", "reason_code": "OK",
                       "duration_ms": int((time.monotonic() - _t0) * 1000),
                       "impact_scope": result})
    return result
