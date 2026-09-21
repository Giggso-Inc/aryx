"""Oracle Property Graph reader — queries ADB 26ai backing tables with SQL/PGQ.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`oracle_graph_reader_helpers.py` (row-mapping), `oracle_graph_reader_basic.py`
(`_OracleGraphBasicReadMixin`), `oracle_graph_reader_neighbors.py`
(`_OracleGraphNeighborsMixin`), and `oracle_graph_reader_traverse.py`
(`_OracleGraphTraverseMixin`), all mixed into `OracleGraphReader` here.
Zero whitebox test patches exist anywhere against
`aryx.graph.oracle_graph_reader.*` (confirmed via grep;
`test_oracle_graph_reader_shortest_path_scope.py` exercises the real
class), so the split was purely mechanical — same pattern already
established for `FalkorStore`/`OracleGraphStore` earlier in this plan.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from aryx.config import get_settings
from aryx.graph.oracle_graph_reader_basic import _OracleGraphBasicReadMixin
from aryx.graph.oracle_graph_reader_neighbors import _OracleGraphNeighborsMixin
from aryx.graph.oracle_graph_reader_traverse import _OracleGraphTraverseMixin

__all__ = ["OracleGraphReader"]


class OracleGraphReader(
    _OracleGraphBasicReadMixin, _OracleGraphNeighborsMixin, _OracleGraphTraverseMixin,
):
    """Reads entities, relationships, and provenance from Oracle ADB 26ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Connect to Oracle ADB and scope all reads to workspace_id."""
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    @property
    def graph_name(self) -> str:
        """Cache-key-safe identifier for this reader's scope.

        Mirrors GraphReader.graph_name (FalkorDB) so callers like
        aryx.graph.retrieve.all_types() can key a cache off either reader
        without branching on backend.
        """
        return f"oracle::{self._workspace_id}"

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Acquire a pooled connection with the graph query timeout applied.

        Mirrors GraphReader._query()'s ARYX_GRAPH_QUERY_TIMEOUT guard for
        FalkorDB — without it, a pathological graph query can hang a request
        indefinitely on Oracle the same way an unbounded Cypher query could
        on FalkorDB before that fix. Reuses the same setting/default (30s)
        since both readers serve the same graph endpoints uniformly.
        """
        with self._pool.connection() as conn:
            conn.call_timeout = get_settings().graph_query_timeout
            yield conn
