"""OracleGraphReader.graph_name and shortest_path() workspace scoping.

Regression coverage for a real post-merge-review finding:

1. graph_name was missing entirely -- aryx.graph.retrieve.all_types() calls
   reader.graph_name to key its TTL cache, which only existed on the
   FalkorDB GraphReader. Any /ask call on the Oracle graph backend crashed
   with AttributeError.
2. shortest_path()'s GRAPH_TABLE MATCH SHORTEST clause filtered only
   entity_id on both path endpoints, with no workspace_id predicate --
   a caller could traverse into/return path data touching a different
   workspace's vertices given its raw entity_id.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.oracle_graph_reader import OracleGraphReader


def _make_reader(fetchall_return=None):
    with patch("aryx.store.oracle_pool.get_oracle_pool") as mock_get_pool:
        mock_pool = MagicMock()
        mock_get_pool.return_value = mock_pool
        reader = OracleGraphReader("tcps://test:1522/db", workspace_id=7)
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_return or []
    mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
    return reader, cur


def test_graph_name_is_workspace_scoped_and_distinct_per_workspace():
    reader_a, _ = _make_reader()
    with patch("aryx.store.oracle_pool.get_oracle_pool"):
        reader_b = OracleGraphReader("tcps://test:1522/db", workspace_id=8)
    assert reader_a.graph_name != reader_b.graph_name
    assert "7" in reader_a.graph_name


def test_all_types_works_with_oracle_reader_via_graph_name():
    """The exact crash this closes: all_types() indexed its cache off
    reader.graph_name, which OracleGraphReader previously lacked."""
    from aryx.graph.retrieve import _types_cache, all_types

    reader, cur = _make_reader()
    with patch.object(OracleGraphReader, "distinct_types", return_value=["Widget", "Gadget"]):
        _types_cache.pop(reader.graph_name, None)
        result = all_types(reader)
    assert result == ["Gadget", "Widget"]


def test_shortest_path_scopes_both_endpoints_to_workspace():
    reader, cur = _make_reader(fetchall_return=[(1, "HAS_PART", 2)])
    reader.shortest_path(src=1, dst=2)

    # shortest_path() issues the GRAPH_TABLE query first, then a follow-up
    # get_entity() per path vertex for detail resolution -- check the first call.
    executed_sql, params = cur.execute.call_args_list[0][0]
    assert "a.workspace_id = :ws" in executed_sql
    assert "b.workspace_id = :ws2" in executed_sql
    assert params["ws"] == 7
    assert params["ws2"] == 7
    assert params["src"] == 1
    assert params["dst"] == 2
