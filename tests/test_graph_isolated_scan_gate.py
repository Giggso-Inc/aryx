"""GraphReader.subgraph() Step 6 — isolated-entity debug scan size gate.

Real incident: GET /graph?workspace_id=44 returned 500
(redis.exceptions.ResponseError: Query timed out) even after indexing
REL.name fixed the endpoint's other slow queries. Root cause #2: Step 6's
`MATCH (e:Entity) WHERE NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-() ...` is a
structural "has zero edges" check across every Entity node — no index
accelerates it. Confirmed live: ~16.5s on a 344,961-entity workspace, ~3.3x
over FalkorDB's default 5000ms timeout. Fix: skip the scan above a
configurable entity-count threshold, checked via one cheap COUNT query
first.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.reader import GraphReader


def _mock_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


def _run_subgraph(total_entities: int, max_scan: int, graph_name: str):
    """Build a GraphReader whose graph reports no entity types (so
    subgraph() skips straight past steps 2-5 to Step 6), call subgraph(),
    and return every query issued. Construction AND the subgraph() call
    both happen inside the same patch context — get_settings() is read
    live inside subgraph() itself, so the mock must still be active when
    that call runs, not just while the reader is constructed.

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
        if "count(e)" in cypher:
            return _mock_result([[total_entities]])
        if "NOT (e)-[:REL]-()" in cypher:
            return _mock_result([])  # the expensive scan itself
        return _mock_result([])

    mock_graph.query.side_effect = _query_side_effect

    with patch("aryx.graph.reader.FalkorDB") as MockDB, \
         patch("aryx.graph.reader.get_settings") as mock_cfg:
        mock_cfg.return_value.graph_query_limit = 2000
        mock_cfg.return_value.graph_isolated_scan_max_entities = max_scan
        mock_cfg.return_value.graph_query_timeout = 30_000
        MockDB.return_value.select_graph.return_value = mock_graph
        reader = GraphReader("redis://localhost:6379")
        reader.subgraph()

    return mock_graph.query.call_args_list


def test_isolated_scan_runs_when_under_threshold():
    calls = _run_subgraph(total_entities=500, max_scan=100_000, graph_name="aryx_ws_test_under")
    scan_calls = [c for c in calls if "NOT (e)-[:REL]-()" in c.args[0]]
    assert len(scan_calls) == 1


def test_isolated_scan_skipped_when_over_threshold():
    """The exact incident: a 344,961-entity graph must not attempt the
    unindexed full scan — only the cheap COUNT query runs."""
    calls = _run_subgraph(total_entities=344_961, max_scan=100_000, graph_name="aryx_ws_test_over")
    scan_calls = [c for c in calls if "NOT (e)-[:REL]-()" in c.args[0]]
    assert scan_calls == []
    count_calls = [c for c in calls if "count(e)" in c.args[0]]
    assert len(count_calls) == 1


def test_isolated_scan_threshold_is_configurable():
    """A workspace just over a LOWER configured threshold is also skipped —
    proves the gate reads the config value, not a hardcoded number."""
    calls = _run_subgraph(total_entities=200, max_scan=100, graph_name="aryx_ws_test_configurable")
    scan_calls = [c for c in calls if "NOT (e)-[:REL]-()" in c.args[0]]
    assert scan_calls == []
