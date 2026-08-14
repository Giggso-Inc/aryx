"""docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_PERFORMANCE_PLAN_2026_08_10.md
-- GraphReader.neighbors_batch() replaces load_product_config's per-attribute
neighbors() loop (confirmed live: 498 calls, 6.85s) with one Cypher query for
many entity ids at once.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_query_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


def _make_reader(rows):
    from aryx.graph import client_pool
    from aryx.graph.reader import GraphReader

    # client_pool caches one FalkorDB client per (host, port) process-wide
    # (aryx.graph.client_pool, G-FalkorDB-pool) — clear it so each test gets
    # a fresh mock instead of a previous test's cached client/select_graph.
    client_pool._clients.clear()
    mock_graph = MagicMock()
    mock_graph.query.return_value = _mock_query_result(rows)
    with patch("aryx.graph.client_pool.FalkorDB") as MockDB, \
         patch("aryx.graph.reader.get_settings") as mock_cfg:
        mock_cfg.return_value.graph_query_timeout = 30_000
        MockDB.return_value.select_graph.return_value = mock_graph
        reader = GraphReader("redis://localhost:6379")
    return reader, mock_graph


def test_empty_entity_ids_short_circuits_without_querying():
    reader, mock_graph = _make_reader([])
    result = reader.neighbors_batch([])
    assert result == {}
    mock_graph.query.assert_not_called()


def test_groups_neighbors_by_source_entity_id():
    rows = [
        [1, 10, "MenuItem", "Yes", {"item_value": "Y"}, "HAS_OPTION", "out"],
        [1, 11, "MenuItem", "No", {"item_value": "N"}, "HAS_OPTION", "out"],
        [2, 20, "MenuItem", "Maybe", {"item_value": "M"}, "HAS_OPTION", "out"],
    ]
    reader, _ = _make_reader(rows)
    result = reader.neighbors_batch([1, 2])

    assert set(result.keys()) == {1, 2}
    assert [n["id"] for n in result[1]] == [10, 11]
    assert [n["id"] for n in result[2]] == [20]
    assert result[1][0]["direction"] == "out"
    assert result[1][0]["relationship"] == "HAS_OPTION"


def test_entity_with_no_neighbors_is_absent_from_result():
    rows = [[1, 10, "MenuItem", "Yes", {}, "HAS_OPTION", "out"]]
    reader, _ = _make_reader(rows)
    result = reader.neighbors_batch([1, 2])

    assert 1 in result
    assert 2 not in result


def test_passes_all_ids_to_the_query():
    reader, mock_graph = _make_reader([])
    reader.neighbors_batch([5, 6, 7])

    args, _ = mock_graph.query.call_args
    assert args[1]["ids"] == [5, 6, 7]
