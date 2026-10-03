"""Write a raw-graph projection to whichever backend is configured.

Backend choice is delegated entirely to the existing
``Settings.effective_graph_backend()`` switch — the same one
``aryx.pipeline.orchestrate.run_pipeline()`` uses for the curated-graph
Project stage — so this module never branches on an environment name
itself; it only asks the existing setting.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from aryx.config import get_settings
from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.naming import raw_workspace_id, raw_ws_graph
from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection, RawGraphWriteResult
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


class RawGraphStore(Protocol):
    """The subset of FalkorStore/OracleGraphStore this module relies on.

    Both concrete stores already implement this shape (see
    ``aryx.graph.falkor_store.FalkorStore`` and
    ``aryx.graph.oracle_graph_store.OracleGraphStore`` — the latter also via
    its ``_OracleGraphBatchMixin``), so no adapter class is needed; this
    Protocol exists purely to document and type-check the contract.
    """

    def clear(self) -> None: ...

    def add_entities_batch(
        self,
        entities: list[tuple[int, str, dict, list[str] | None, str | None]],
        *,
        full_rebuild: bool = False,
        **kwargs: object,
    ) -> int: ...

    def add_relationships_batch(
        self,
        rels: list[tuple[int, int, str]],
        *,
        full_rebuild: bool = False,
        **kwargs: object,
    ) -> object: ...


def get_raw_graph_store(workspace_id: int, source_key: str, *, dsn: str, graph_url: str) -> RawGraphStore:
    """Return a raw-graph store scoped to one source file within ``workspace_id``.

    Args:
        workspace_id: The *curated* workspace id this raw graph belongs to.
        source_key: Per-file identifier, unique within the job — in
            practice the uploaded filename's stem. The raw graph is stored
            under a scope derived from *both* workspace_id and source_key
            (see ``aryx.cpq_ingestion.naming``) so that uploading several
            XML files to the same workspace in one job gives each file its
            own independent raw graph instead of each write clearing the
            previous file's.
        dsn: Oracle ADB connection string (used only on the oci_graph backend).
        graph_url: FalkorDB connection URL (used only on the falkordb backend).
    """
    settings = get_settings()
    if settings.effective_graph_backend() == "oci_graph":
        from aryx.graph.oracle_graph_store import OracleGraphStore  # optional OCI dep — lazy import

        offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
        return OracleGraphStore(dsn, raw_workspace_id(workspace_id, offset, source_key))
    from aryx.graph.falkor_store import FalkorStore

    return FalkorStore(graph_url, raw_ws_graph(workspace_id, source_key))


def _graph_ref(workspace_id: int, source_key: str) -> str:
    """Human-readable identifier for the raw graph's storage scope, for logging/results."""
    settings = get_settings()
    if settings.effective_graph_backend() == "oci_graph":
        offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
        return f"workspace_id={raw_workspace_id(workspace_id, offset, source_key)}"
    return f"graph={raw_ws_graph(workspace_id, source_key)}"


def write_raw_graph(
    projection: RawGraphProjection,
    *,
    workspace_id: int,
    source_key: str,
    dsn: str,
    graph_url: str,
    should_stop: "Callable[[], bool] | None" = None,
) -> RawGraphWriteResult:
    """Clear and rewrite one file's raw graph within ``workspace_id`` from ``projection``.

    Always a full rebuild of that file's own scope (mirrors the curated
    graph's own clear()-then-write contract) — the raw graph is a
    rebuildable projection of one source file, not a store of record.
    Every batch write passes ``full_rebuild=True``: the immediately-preceding
    ``clear()`` already guarantees no existing rows can conflict, so the
    plain-INSERT path is safe and, on the Oracle backend, avoids a
    documented, live-confirmed 180+ second MERGE-executemany() hang that the
    default (``full_rebuild=False``) path would otherwise silently take on
    every write (see ``OracleGraphStore.add_entities_batch``'s docstring).

    should_stop — forwarded to the store's batch methods (see
    ``OracleGraphStore.add_entities_batch``'s docstring for the convention:
    checked per-chunk, stops without raising, keeps whatever was already
    written). Previously this function had no way to interrupt a write in
    progress at all: a cancelled job's ~11,700-chunk vertex+edge write for a
    240MB file kept running for tens of minutes after "cancel" took effect
    everywhere else, which is exactly the gap this closes. A should_stop
    hit here leaves this file's raw graph genuinely partial (some nodes/
    edges written, the rest missing) — accepted, since the raw graph is
    documented above as "a rebuildable projection of one source file, not a
    store of record": the next (non-cancelled) ingest of the same file
    clear()s and fully rewrites this scope regardless.
    """
    backend = get_settings().effective_graph_backend()
    graph_ref = _graph_ref(workspace_id, source_key)
    logger.debug(
        "cpq_ingestion: writing raw graph workspace_id=%s source_key=%s backend=%s %s nodes=%d edges=%d",
        workspace_id, source_key, backend, graph_ref, len(projection.nodes), len(projection.edges),
    )
    store = get_raw_graph_store(workspace_id, source_key, dsn=dsn, graph_url=graph_url)
    raven_log("DEBUG", "P4", "ingest.raw_graph.write clearing and rewriting file scope",
              context={"workspace_id": workspace_id, "source_key": source_key, "backend": backend,
                       "graph_ref": graph_ref, "nodes": len(projection.nodes), "edges": len(projection.edges),
                       "selected_option": "full_rebuild", "reason_code": "CLEAR_THEN_WRITE"})
    store.clear()
    entities = [(n.id, n.tag, n.properties, None, None) for n in projection.nodes]
    relationships = [(e.source_id, e.target_id, e.name) for e in projection.edges]
    if entities:
        store.add_entities_batch(entities, full_rebuild=True, should_stop=should_stop)
    if relationships and (should_stop is None or not should_stop()):
        store.add_relationships_batch(relationships, full_rebuild=True, should_stop=should_stop)
    return RawGraphWriteResult(
        nodes_written=len(projection.nodes),
        edges_written=len(projection.edges),
        backend=backend,
        graph_ref=graph_ref,
    )


def project_and_write_raw_graph(
    data: bytes,
    *,
    workspace_id: int,
    source_key: str,
    dsn: str,
    graph_url: str,
    should_stop: "Callable[[], bool] | None" = None,
) -> RawGraphWriteResult:
    """Convenience wrapper: parse XML and write the resulting raw graph in one call."""
    projection = project_xml_to_raw_graph(data)
    projection = _with_query_tables(projection)
    return write_raw_graph(
        projection, workspace_id=workspace_id, source_key=source_key, dsn=dsn, graph_url=graph_url,
        should_stop=should_stop,
    )


def _with_query_tables(projection: RawGraphProjection) -> RawGraphProjection:
    """Opt-in (``ARYX_CSV_BML_ENABLED``): record on each node which tables its SQL queries read.

    The store clips string properties to ~200 chars, so script text cannot be searched later;
    short list properties survive. Best-effort: any failure keeps the plain projection.
    """
    from aryx.csv_bml_ingestion.config import csv_bml_enabled  # lazy: avoids an import cycle

    if not csv_bml_enabled():
        return projection
    try:
        from aryx.csv_bml_ingestion.bml_graph import enrich_projection

        return enrich_projection(projection)
    except Exception as exc:  # noqa: BLE001 -- the raw graph is a best-effort provenance layer
        logger.warning("cpq_ingestion: query-table enrichment failed; writing the plain raw graph", exc_info=True)
        raven_log("WARN", "P3", "ingest.raw_graph.enrich_failed query-table enrichment skipped, plain graph written",
                  error_code="ARYX_ING_RAW_GRAPH_ENRICH_FAILED",
                  context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                           "backoff_ms": 0, "recovery_selected": "plain_projection", "fallback_target": None,
                           "exit_condition": "degraded", "result": "degraded"})
        return projection
