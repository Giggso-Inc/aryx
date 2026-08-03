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


def test_mark_isolated_entities_scoped_to_entity_ids_restricts_the_match(): # noqa: E501
    """Raven review, PR #147 finding #2: project_incremental must not pay a
    full-graph-scan cost proportional to total graph size on every small
    dirty-set update — passing entity_ids scopes both passes to just those
    ids instead of scanning every Entity."""
    store, mock_graph = _store()
    store.mark_isolated_entities(entity_ids=[10, 20, 30])

    calls = mock_graph.query.call_args_list
    for call in calls:
        cypher, params = call.args[0], call.args[1]
        assert "e.id IN $ids" in cypher
        assert params["ids"] == [10, 20, 30]


def test_mark_isolated_entities_empty_scope_is_a_no_op():
    """An incremental run with nothing dirty and no tombstones has an empty
    scope — must not issue any queries at all, not even a harmless UNWIND
    over nothing."""
    store, mock_graph = _store()
    store.mark_isolated_entities(entity_ids=[])

    mock_graph.query.assert_not_called()


def test_mark_isolated_entities_unscoped_still_matches_the_whole_graph():
    """project_graph (full rebuild) passes no entity_ids — every entity
    needs a fresh isolated flag either way, so the full scan is the
    already-correct cost there, not a regression to guard against."""
    store, mock_graph = _store()
    store.mark_isolated_entities()

    calls = [c.args[0] for c in mock_graph.query.call_args_list]
    assert not any("e.id IN $ids" in c for c in calls)


def test_mark_isolated_entities_swallows_query_failures():
    """Raven review, PR #147 finding #1: mark_isolated_entities() runs the
    exact same structural full-graph scan that used to time out on large
    workspaces (per this module's own docstring) — just now inside the
    write path instead of a read. A failure here (e.g. that same timeout,
    now during ingest) must degrade to a stale/missing `isolated` flag,
    never abort the whole project_graph/project_incremental run — mirrors
    ensure_indexes()'s existing try/except immediately above it."""
    store, mock_graph = _store()
    mock_graph.query.side_effect = Exception("Query timed out")

    store.mark_isolated_entities()  # must not raise


def test_neighbor_ids_returns_distinct_connected_entity_ids():
    store, mock_graph = _store()
    mock_result = MagicMock()
    mock_result.result_set = [[1], [2], [1]]
    mock_graph.query.return_value = mock_result

    ids = store.neighbor_ids([99])

    assert ids == [1, 2, 1]  # de-dup is Cypher's job (DISTINCT); pass-through here
    cypher, params = mock_graph.query.call_args.args[0], mock_graph.query.call_args.args[1]
    assert "UNWIND $ids" in cypher
    assert params["ids"] == [99]


def test_neighbor_ids_empty_input_issues_no_query():
    store, mock_graph = _store()
    assert store.neighbor_ids([]) == []
    mock_graph.query.assert_not_called()
