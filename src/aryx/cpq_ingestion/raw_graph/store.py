"""Write a raw-graph projection to whichever backend is configured.

Backend choice is delegated entirely to the existing
``Settings.effective_graph_backend()`` switch — the same one
``aryx.pipeline.orchestrate.run_pipeline()`` uses for the curated-graph
Project stage — so this module never branches on an environment name
itself; it only asks the existing setting.
"""
from __future__ import annotations

from typing import Protocol

from aryx.config import get_settings
from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.naming import raw_workspace_id, raw_ws_graph
from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection, RawGraphWriteResult
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph


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
        **kwargs: object,
    ) -> int: ...

    def add_relationships_batch(
        self,
        rels: list[tuple[int, int, str]],
        **kwargs: object,
    ) -> object: ...


def get_raw_graph_store(workspace_id: int, *, dsn: str, graph_url: str) -> RawGraphStore:
    """Return a raw-graph store scoped to ``workspace_id``, for the active backend.

    Args:
        workspace_id: The *curated* workspace id this raw graph belongs to.
            The raw graph itself is stored under a derived, non-colliding
            scope (see ``aryx.cpq_ingestion.naming``).
        dsn: Oracle ADB connection string (used only on the oci_graph backend).
        graph_url: FalkorDB connection URL (used only on the falkordb backend).
    """
    settings = get_settings()
    if settings.effective_graph_backend() == "oci_graph":
        from aryx.graph.oracle_graph_store import OracleGraphStore  # optional OCI dep — lazy import

        offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
        return OracleGraphStore(dsn, raw_workspace_id(workspace_id, offset))
    from aryx.graph.falkor_store import FalkorStore

    return FalkorStore(graph_url, raw_ws_graph(workspace_id))


def _graph_ref(workspace_id: int) -> str:
    """Human-readable identifier for the raw graph's storage scope, for logging/results."""
    settings = get_settings()
    if settings.effective_graph_backend() == "oci_graph":
        offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
        return f"workspace_id={raw_workspace_id(workspace_id, offset)}"
    return f"graph={raw_ws_graph(workspace_id)}"


def write_raw_graph(
    projection: RawGraphProjection,
    *,
    workspace_id: int,
    dsn: str,
    graph_url: str,
) -> RawGraphWriteResult:
    """Clear and rewrite the raw graph for ``workspace_id`` from ``projection``.

    Always a full rebuild (mirrors the curated graph's own clear()-then-write
    contract) — the raw graph is a rebuildable projection of the source XML,
    not a store of record.
    """
    store = get_raw_graph_store(workspace_id, dsn=dsn, graph_url=graph_url)
    store.clear()
    entities = [(n.id, n.tag, n.properties, None, None) for n in projection.nodes]
    relationships = [(e.source_id, e.target_id, e.name) for e in projection.edges]
    if entities:
        store.add_entities_batch(entities)
    if relationships:
        store.add_relationships_batch(relationships)
    return RawGraphWriteResult(
        nodes_written=len(projection.nodes),
        edges_written=len(projection.edges),
        backend=get_settings().effective_graph_backend(),
        graph_ref=_graph_ref(workspace_id),
    )


def project_and_write_raw_graph(
    data: bytes,
    *,
    workspace_id: int,
    dsn: str,
    graph_url: str,
) -> RawGraphWriteResult:
    """Convenience wrapper: parse XML and write the resulting raw graph in one call."""
    projection = project_xml_to_raw_graph(data)
    return write_raw_graph(projection, workspace_id=workspace_id, dsn=dsn, graph_url=graph_url)
