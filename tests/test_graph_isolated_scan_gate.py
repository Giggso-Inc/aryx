"""GraphReader.subgraph() Step 6 — isolated-entity lookup.

Real incident: GET /graph?workspace_id=44 returned 500
(redis.exceptions.ResponseError: Query timed out) even after indexing
REL.name fixed the endpoint's other slow queries. Root cause #2: Step 6's
`MATCH (e:Entity) WHERE NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-() ...` is a
structural "has zero edges" check across every Entity node — no index
accelerates it. An entity-count size gate (skip the scan above a threshold)
patched the crash but meant isolated nodes silently stopped appearing once a
workspace grew past that threshold, and any workspace slow enough could
still time out below it.

docs/graph_isolated_scan_gate — fixed at the source instead:
FalkorStore.mark_isolated_entities() now stamps every Entity's `isolated`
boolean once, at projection time, with an index on that property. Step 6
reads that indexed property directly — a cheap lookup regardless of graph
size, no gate needed at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.reader import GraphReader


def _mock_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


def _run_subgraph(iso_rows: list, graph_name: str):
    """Build a GraphReader whose graph reports no entity types (so
    subgraph() skips straight past steps 2-5 to Step 6), call subgraph(),
    and return every query issued plus the final result.

    graph_name must be unique per call: subgraph() caches its result by
    (graph name, capped) for 30s — reusing the same name across tests in
    the same run would make a later test silently hit an earlier test's
    cached result instead of issuing any queries at all.
    """
    mock_graph = MagicMock()
    mock_graph.name = graph_name

    def _query_side_effect(cypher, params=None, timeout=None):
        if "DISTINCT e.type" in cypher:
            return _mock_result([])  # no entity types -> steps 2-5 no-op
        if "isolated: true" in cypher:
            return _mock_result(iso_rows)
        return _mock_result([])

    mock_graph.query.side_effect = _query_side_effect

    from aryx.graph import client_pool
    client_pool._clients.clear()
    with patch("aryx.graph.client_pool.FalkorDB") as MockDB, \
         patch("aryx.graph.reader.get_settings") as mock_cfg:
        mock_cfg.return_value.graph_query_limit = 2000
        mock_cfg.return_value.graph_query_timeout = 30_000
        MockDB.return_value.select_graph.return_value = mock_graph
        reader = GraphReader("redis://localhost:6379")
        result = reader.subgraph()

    return mock_graph.query.call_args_list, result


def test_isolated_lookup_uses_indexed_property_not_a_live_scan():
    """The query issued for Step 6 must be the indexed {isolated: true}
    lookup — never the old unindexed NOT (e)-[:REL]-() structural scan,
    regardless of graph size (no size gate exists to skip it any more)."""
    calls, _ = _run_subgraph(iso_rows=[], graph_name="aryx_ws_test_indexed")
    live_scan_calls = [c for c in calls if "NOT (e)-[:REL]-()" in c.args[0]]
    assert live_scan_calls == []
    indexed_calls = [c for c in calls if "isolated: true" in c.args[0]]
    assert len(indexed_calls) == 1


def test_isolated_entities_are_included_in_the_result():
    iso_rows = [[99, "Widget", "Lonely Widget", {}]]
    _, result = _run_subgraph(iso_rows=iso_rows, graph_name="aryx_ws_test_included")
    ids = [e["id"] for e in result["entities"]]
    assert 99 in ids


def test_no_isolated_entities_is_not_an_error():
    _, result = _run_subgraph(iso_rows=[], graph_name="aryx_ws_test_none")
    assert result["entities"] == []
    assert result["relationships"] == []
