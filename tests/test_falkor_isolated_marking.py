"""FalkorStore.mark_isolated_entities() — docs/graph_isolated_scan_gate.

GraphReader.subgraph()'s Step 6 (isolated-entity debug visibility) used to
compute "has zero edges" live, per /graph request — an unindexed full-graph
scan that timed out on large workspaces (see test_graph_isolated_scan_gate.py
for the read side). The fix moves that computation to projection time: this
module stamps every Entity's `isolated` boolean once per ingest run, and
ensure_indexes() adds an index on it so reads are a cheap indexed lookup.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.falkor_store import FalkorStore


def _store() -> FalkorStore:
    with patch("aryx.graph.falkor_store.FalkorDB") as MockDB:
        mock_graph = MagicMock()
        MockDB.return_value.select_graph.return_value = mock_graph
        store = FalkorStore("redis://localhost:6379", graph="aryx_test")
        return store, mock_graph


def test_mark_isolated_entities_issues_true_then_false_passes():
    store, mock_graph = _store()
    store.mark_isolated_entities()

    calls = [c.args[0] for c in mock_graph.query.call_args_list]
    true_calls = [c for c in calls if "isolated = true" in c]
    false_calls = [c for c in calls if "isolated = false" in c]
    assert len(true_calls) == 1
    assert len(false_calls) == 1
    # The true-pass must match the same "zero edges in either direction"
    # structural condition Step 6 used to check live.
    assert "NOT (e)-[:REL]-()" in true_calls[0]
    assert "NOT (e)<-[:REL]-()" in true_calls[0]


def test_ensure_indexes_creates_index_on_isolated_property():
    store, mock_graph = _store()
    store.ensure_indexes()

    calls = [c.args[0] for c in mock_graph.query.call_args_list]
    assert any("Entity.isolated" in c or "e.isolated" in c for c in calls)
