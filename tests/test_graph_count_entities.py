"""GraphReader.count_entities() / OracleGraphReader.count_entities().

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: ask_overview.py and
observability_api.py both used len(find_entities(limit=500)) to report an
entity count, silently under-reporting any workspace with more than 500
entities. count_entities() issues a true COUNT/count(e) query instead of
scanning a capped page.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.oracle_graph_reader import OracleGraphReader
from aryx.graph.reader import GraphReader


# ---------------------------------------------------------------------------
# FalkorDB (GraphReader)
# ---------------------------------------------------------------------------

def _make_falkor_reader(query_return):
    reader = GraphReader.__new__(GraphReader)
    reader._query = MagicMock(return_value=query_return)
    return reader


def test_falkor_count_entities_total_uses_count_query_not_a_scan():
    reader = _make_falkor_reader([[1234]])
    assert reader.count_entities() == 1234
    cypher, params = reader._query.call_args[0][0], (reader._query.call_args[0][1:] or ({},))[0]
    assert "count(e)" in cypher
    assert "$t" not in cypher


def test_falkor_count_entities_scoped_to_type():
    reader = _make_falkor_reader([[7]])
    assert reader.count_entities("Widget") == 7
    cypher, params = reader._query.call_args[0]
    assert "{type: $t}" in cypher
    assert params == {"t": "Widget"}


def test_falkor_count_entities_empty_graph_returns_zero():
    reader = _make_falkor_reader([])
    assert reader.count_entities() == 0


# ---------------------------------------------------------------------------
# Oracle (OracleGraphReader)
# ---------------------------------------------------------------------------

def _make_oracle_reader(fetchone_return):
    with patch("aryx.store.oracle_pool.get_oracle_pool") as mock_get_pool:
        mock_pool = MagicMock()
        mock_get_pool.return_value = mock_pool
        reader = OracleGraphReader("tcps://test:1522/db", workspace_id=7)
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
    return reader, cur


def test_oracle_count_entities_total_is_workspace_scoped():
    reader, cur = _make_oracle_reader((900,))
    assert reader.count_entities() == 900
    sql, params = cur.execute.call_args[0]
    assert "COUNT(*)" in sql
    assert params == (7,)


def test_oracle_count_entities_scoped_to_type_adds_type_predicate():
    reader, cur = _make_oracle_reader((42,))
    assert reader.count_entities("Widget") == 42
    sql, params = cur.execute.call_args[0]
    assert "type = :2" in sql
    assert params == (7, "Widget")


def test_oracle_count_entities_no_row_returns_zero():
    reader, cur = _make_oracle_reader(None)
    assert reader.count_entities() == 0
