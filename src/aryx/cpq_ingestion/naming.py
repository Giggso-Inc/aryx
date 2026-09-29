"""Naming for the raw graph's storage scope — kept separate from the curated graph.

Mirrors ``aryx.naming.ws_graph`` (FalkorDB graph name per workspace) but for
the raw layer, which must not share storage with the curated graph: the
curated graph's projection wipes and rebuilds its own scope on every run
(``FalkorStore.clear()`` / ``OracleGraphStore.clear()``), which would
otherwise delete the raw nodes it is meant to sit alongside as a provenance
layer.
"""
from __future__ import annotations


def raw_ws_graph(workspace_id: int) -> str:
    """FalkorDB graph name for a workspace's raw graph."""
    return f"aryx_raw_ws_{int(workspace_id)}"


def raw_workspace_id(workspace_id: int, offset: int) -> int:
    """Oracle Graph workspace_id for a workspace's raw graph.

    ``aryx_graph_vertex``/``aryx_graph_edge`` scope rows by a plain
    ``workspace_id`` column (no foreign key to ``aryx_workspace``, no
    raw/curated discriminator column), so the raw graph is given a distinct,
    deterministic workspace_id derived from the curated one instead of
    sharing its scope.
    """
    return int(workspace_id) + int(offset)
