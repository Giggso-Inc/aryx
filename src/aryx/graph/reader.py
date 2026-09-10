"""FalkorDB reader for the knowledge-graph projection (Increment 6).

Read counterpart to FalkorStore: looks up resolved entities, traverses their
one-hop relationships in both directions, and threads back to the source
records each entity was discovered in. Queries return scalar properties (never
raw Node objects) so callers get plain, serializable dicts.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the entity-row
mapping (`_entity`/`_parse_attrs`) lives in `graph.reader_entity`; every query
implementation that doesn't itself call `get_settings()` lives in
`graph.reader_queries` as a pure function taking the bound `_query` method
(no whitebox patch to retarget, since none of them touched `get_settings`/
`FalkorDB` directly); and the `subgraph()` canvas-building algorithm lives in
`graph.reader_subgraph`. `find_entities()` and `subgraph()` stay as real
methods here (each computing its own `capped` from `get_settings()` before
delegating) so the `aryx.graph.reader.get_settings` whitebox patches used
across `test_graph_query_timeout_and_export_cap.py`,
`test_graph_isolated_scan_gate.py`, and `test_scalability_fixes.py` keep
intercepting them unchanged.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from aryx.config import get_settings
from aryx.graph.reader_queries import (
    _all_relationships,
    _describe_schema,
    _distinct_types,
    _find_entities,
    _get_entity,
    _neighbors,
    _neighbors_batch,
    _provenance,
    _shortest_path,
)
from aryx.graph.reader_subgraph import _build_subgraph

logger = logging.getLogger(__name__)


class GraphReader:
    """Reads entities, relationships and provenance from the FalkorDB graph."""

    def __init__(self, url: str, graph: str = "aryx") -> None:
        """Connect from a redis:// URL and select a named graph.

        Args:
            url: FalkorDB connection URL, e.g. redis://falkordb:6379.
            graph: Graph key to read from.
        """
        parsed = urlparse(url)
        self._conn_kwargs = dict(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            username=parsed.username or None,
            password=parsed.password or None,
        )
        self._graph_name = graph
        self._db = FalkorDB(**self._conn_kwargs)
        self._graph = self._db.select_graph(graph)

    @property
    def graph_name(self) -> str:
        """The workspace-scoped graph key this reader selects — cache-key-safe."""
        return self._graph.name

    def _new_connection(self):
        """Open an independent FalkorDB connection selecting this reader's
        graph — used by subgraph()'s per-relationship-type worker threads,
        since redis-py connections cannot be shared safely across threads."""
        return FalkorDB(**self._conn_kwargs).select_graph(self._graph_name)

    def _query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """Execute a Cypher query and return its result rows.

        `timeout_ms` (`ARYX_GRAPH_QUERY_TIMEOUT`, PR #121): caps how long
        FalkorDB will run any single query before aborting it — without this,
        a pathological query on a large workspace can hang the whole request
        indefinitely instead of failing fast.

        No per-query INFO-level logging here (2026-07-28): it flooded
        container logs on every graph read, drowning out other INFO-level
        diagnostics — see the earlier removal commit for the live-verified
        rationale.
        """
        timeout_ms = get_settings().graph_query_timeout or None
        return self._graph.query(cypher, params or {}, timeout=timeout_ms).result_set

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return a single entity's id/type/name/attributes, or None if absent."""
        return _get_entity(self._query, entity_id)

    def distinct_types(self) -> list[str]:
        """Every distinct entity type in the graph — deterministic, no sampling."""
        return _distinct_types(self._query)

    def describe_schema(self, sample_per_type: int = 25) -> dict[str, Any]:
        """Describe the graph schema as it actually exists, for query generation."""
        return _describe_schema(self._query, self.distinct_types(), sample_per_type)

    def find_entities(self, ontology_type: str | None = None,
                      name: str | None = None, limit: int = 50,
                      offset: int = 0) -> list[dict[str, Any]]:
        """Find entities filtered by type and/or case-insensitive name match.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            limit: Maximum rows to return (coerced to int, capped at ARYX_GRAPH_QUERY_LIMIT).
            offset: Rows to skip before applying limit — paginate a
                single ontology_type past the ARYX_GRAPH_QUERY_LIMIT cap by
                calling repeatedly with offset += limit until a short page
                comes back (see CpqEngine.load_product_config's FK-fallback,
                confirmed live: SL3500e's >2000 bm_menu_item rows silently
                truncated at one capped call otherwise).
        Returns:
            A list of {id, type, name, attributes} dicts.
        """
        capped = max(1, min(int(limit), get_settings().graph_query_limit))
        skip = max(0, int(offset))
        return _find_entities(self._query, ontology_type, name, capped, skip)

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions."""
        return _neighbors(self._query, entity_id)

    def neighbors_batch(self, entity_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """Batch one-hop neighbor lookup for multiple entities in one Cypher round-trip."""
        return _neighbors_batch(self._query, entity_ids)

    def all_relationships(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return relationship edges in the graph, optionally capped."""
        return _all_relationships(self._query, limit)

    def subgraph(self, rel_limit: int = 2000) -> dict[str, Any]:
        """Return a connected subgraph suitable for graph-canvas rendering.

        Algorithm (all steps run per cache miss):
        1. Discover entity types and relationship types.
        2. Sample rels_per_rtype rels per relationship type so every rel class
           is represented and source/target pairs are loaded together.
        3. Greedy per-type cap: process rels from highest combined endpoint
           degree to lowest; include both endpoints only if each type still has
           room under the per_type cap.  Guarantees included entities are hubs
           that connect across types.
        4. Seed any entity type with zero rels so all types appear on canvas.
        5. Post-linking pass: for any entity still without a visible edge, run
           a batched query to find one real neighbor and add it.  Guarantees
           zero isolated nodes in the rendered canvas.
        6. Add truly isolated FalkorDB entities (no edges at all) for debugging.

        Results are cached for 30 s (per graph + rel_limit combination).
        """
        capped = max(1, min(int(rel_limit), get_settings().graph_query_limit))
        timeout_ms = get_settings().graph_query_timeout or None
        return _build_subgraph(
            self._query, self._graph.name, capped, self._new_connection, timeout_ms,
        )

    def provenance(self, entity_id: int) -> list[dict[str, Any]]:
        """Return the source records an entity was projected from."""
        return _provenance(self._query, entity_id)

    def shortest_path(self, src: int, dst: int, max_hops: int = 6) -> list[dict[str, Any]]:
        """Return the shortest path between two entities (either direction), or []."""
        return _shortest_path(self._query, src, dst, max_hops)
