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
from collections.abc import Callable
from typing import Any

from aryx.broker import Broker
from aryx.cpq_ingestion.raw_graph.containment_relate import translate_containment_edges
from aryx.cpq_ingestion.raw_graph.match_key_inference import infer_match_keys_for_tag
from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection
from aryx.cpq_ingestion.raw_graph.store import with_query_tables
from aryx.cpq_ingestion.raw_graph.resolve_adapter import (
    SOURCE_SYSTEM,
    RawGraphConnector,
    group_nodes_by_tag,
    parse_record_id,
)
from aryx.pipeline.orchestrate import PipelineCancelled, project_workspace_graph, run_pipeline
from aryx.store.entity_store import EntityStore

from aryx.raven_log import raven_log

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

    This does NOT touch aryx_entity_member rows for the deleted entities --
    EntityStore.delete_entity() (reused here, not new) already has that
    same limitation for its existing callers, so this is consistent with,
    not worse than, the rest of the codebase. Best-effort: a deletion
    failure is logged and skipped rather than raised, so a DB hiccup while
    cleaning up after a cancel never masks the cancellation itself.
    """
    if not node_id_to_entity_id:
        return
    entity_ids = sorted(set(node_id_to_entity_id.values()))
    deleted = 0
    for entity_id in entity_ids:
        try:
            if estore.delete_entity(entity_id):
                deleted += 1
        except Exception:  # noqa: BLE001 -- cleanup is best-effort, never mask the cancel
            logger.warning(
                "raw_graph resolve_and_relate did=%s source_key=%s: failed to delete "
                "orphaned entity_id=%s after cancel", log_id, source_key, entity_id, exc_info=True,
            )
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
    projection: RawGraphProjection,
    *,
    workspace_id: int,
    source_key: str,
    dsn: str,
    graph_url: str,
    broker: Broker,
    context: str = "",
    log_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Resolve every raw-graph tag into curated entities, relate via
    containment, and project the result into the curated graph.

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

    Mitigated, not eliminated: a cancel mid-loop now deletes (via
    _delete_orphaned_entities, below) every entity already created by
    EARLIER tags in THIS attempt, before raising -- relationships are only
    saved once, after every tag finishes, so a mid-loop cancel's entities
    never had any yet and would otherwise sit as permanent orphans once
    project_workspace_graph next rebuilds the graph from everything in the
    DB. This means a cancelled attempt leaves nothing behind, so the next
    confirm (of this file or anything else in the workspace) starts clean
    rather than piling a retry's entities on top of leftover orphans. It
    does NOT prevent duplication across separate confirm attempts that each
    ran to completion (re-confirming an already-finished file, or a cancel
    that lands after the last tag but before the final project_workspace_
    graph call -- see the trade-off note above, where entities+relationships
    are already correctly saved and nothing needs cleanup). True
    resumability (skipping already-resolved tags, mirroring the generic CSV
    path's completed_plans) is a separate, larger feature and still out of
    scope for this PR.
    """
    total_entities = 0
    relationships: list[Any] = []
    graph_counts: dict[str, int] = {}
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
    node_id_to_entity_id: dict[int, int] = {}
    estore = EntityStore(dsn, workspace_id)
    try:
        for tag, nodes in by_tag.items():
            if should_stop is not None and should_stop():
                _delete_orphaned_entities(estore, node_id_to_entity_id, log_id=log_id, source_key=source_key)
                raise PipelineCancelled(
                    f"job cancelled before tag={tag} source_key={source_key}",
                )
            inferred = infer_match_keys_for_tag(tag, nodes, context, log_id=log_id)
            connector = RawGraphConnector(nodes, tag=tag, source_key=source_key)
            summary = run_pipeline(
                connector=connector, dsn=dsn, system=SOURCE_SYSTEM, dataset=tag,
                ontology_type=inferred["ontology_type"], match_keys=inferred["match_keys"],
                graph_url=graph_url, broker=broker, workspace_id=workspace_id,
                relate=False, skip_graph=True, should_stop=should_stop,
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

        relationships = translate_containment_edges(
            projection.edges, node_id_to_entity_id, log_id=log_id,
        )
        if relationships:
            estore.save_relationships(relationships)

        if should_stop is not None and should_stop():
            raise PipelineCancelled(
                f"job cancelled before final graph projection source_key={source_key}",
            )
        graph_counts = project_workspace_graph(dsn, graph_url, workspace_id, estore)
    finally:
        estore.close()

    result = {"tags": len(by_tag), "entities": total_entities,
              "relationships": len(relationships), **graph_counts}
    logger.info("raw_graph resolve_and_relate complete did=%s source_key=%s %s",
                log_id, source_key, result)
    raven_log("INFO", "P4", "ingest.raw_graph.resolved raw graph resolved into curated graph",
              context={"log_id": log_id, "source_key": source_key, "workspace_id": workspace_id,
                       "tags": len(by_tag), "entities": total_entities, "relationships": len(relationships)})
    return result
