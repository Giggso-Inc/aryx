"""docs/GRAPH_SUBGRAPH_LARGE_WORKSPACE_PERFORMANCE_2026_09_02.md

GET /graph?workspace_id=93 took ~24 minutes end-to-end (elapsed_s=1448-1475
in aryx-api logs) despite every relevant FalkorDB index existing (confirmed
live via CALL db.indexes()) -- ruling out the missing-index theory from the
original REL.name fix. GRAPH.SLOWLOG on the live instance showed each
individual query genuinely slow at this scale (9M relationships / 747K
entities): the two full-graph `DISTINCT ... ORDER BY` type-discovery scans
took 13-28s EACH (no index accelerates a DISTINCT aggregate -- it must touch
every row), and each per-relationship-type sampling query in
GraphReader.subgraph() step 2 took 18-23s despite the r.name index, at this
cardinality. With ~48 relationship types run sequentially, ~48 x ~20s alone
accounts for the ~24 minute wall time.

Fix: (1) cache entity/relationship type discovery (_types_cache) separately
from the 30s subgraph-result cache (_subgraph_cache), with a much longer TTL
(_TYPES_TTL) -- the set of types present changes far less often than the
sampled subgraph. (2) Fan the per-relationship-type queries out over a small
worker pool (_MAX_RTYPE_WORKERS) instead of running them one at a time, each
worker on its own FalkorDB connection since a single redis-py connection
cannot safely serve concurrent callers.
"""
from __future__ import annotations

import contextlib
import threading
from unittest.mock import MagicMock, patch

import aryx.graph.reader_subgraph as reader_mod
from aryx.graph.reader import GraphReader


def _mock_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


@contextlib.contextmanager
def _make_reader(graph_name: str, etype_rows, rtype_rows, rtype_row_map):
    """Build a GraphReader against a mock graph, with FalkorDB patched for
    the whole `with` block -- subgraph() opens fresh connections per worker
    via _new_connection(), so the patch must still be active during the
    subgraph() call itself, not just during __init__.

    query() routes by cypher shape:
      - `DISTINCT e.type` -> etype_rows
      - `DISTINCT r.name` -> rtype_rows
      - the per-relationship-type sampler -> rtype_row_map[params['rname']]
      - anything else (steps 4/5/6) -> []
    """
    call_log: list[tuple] = []
    lock = threading.Lock()

    mock_graph = MagicMock()
    mock_graph.name = graph_name

    def _side_effect(cypher, params=None, timeout=None):
        with lock:
            call_log.append((cypher, params or {}, threading.get_ident()))
        if "DISTINCT e.type" in cypher:
            return _mock_result(etype_rows)
        if "DISTINCT r.name" in cypher:
            return _mock_result(rtype_rows)
        if "r:REL {name: $rname}" in cypher:
            rname = (params or {}).get("rname")
            return _mock_result(rtype_row_map.get(rname, []))
        return _mock_result([])

    mock_graph.query.side_effect = _side_effect

    with patch("aryx.graph.reader.FalkorDB") as MockDB, \
         patch("aryx.graph.reader.get_settings") as mock_cfg:
        mock_cfg.return_value.graph_query_limit = 2000
        mock_cfg.return_value.graph_query_timeout = 30_000
        MockDB.return_value.select_graph.return_value = mock_graph
        reader = GraphReader("redis://localhost:6379")
        yield reader, mock_graph, call_log


def _sample_row(a_id, b_id, rname):
    return [a_id, "TypeA", f"a{a_id}", {}, b_id, "TypeB", f"b{b_id}", {}]


class TestTypeDiscoveryCache:
    def setup_method(self):
        reader_mod._types_cache.clear()
        reader_mod._subgraph_cache.clear()

    def test_second_call_with_different_rel_limit_skips_the_distinct_scans(self):
        """Two subgraph() calls with different rel_limit are separate entries
        in _subgraph_cache (cache miss both times), but must share one
        _types_cache entry -- the expensive DISTINCT scans run once, not
        twice."""
        etype_rows = [["TypeA"], ["TypeB"]]
        rtype_rows = [["R1"]]
        row_map = {"R1": [_sample_row(1, 2, "R1")]}
        with _make_reader(
            "aryx_ws_test_typecache", etype_rows, rtype_rows, row_map
        ) as (reader, mock_graph, calls):
            reader.subgraph(rel_limit=100)
            reader.subgraph(rel_limit=200)  # different cache_key -> real miss

        distinct_calls = [c for c in calls if "DISTINCT" in c[0]]
        assert len(distinct_calls) == 2, (
            "expected exactly one e.type scan + one r.name scan total, "
            f"got {len(distinct_calls)}: {[c[0] for c in distinct_calls]}"
        )

    def test_types_cache_expires_after_its_own_longer_ttl(self):
        etype_rows = [["TypeA"]]
        rtype_rows = [["R1"]]
        row_map = {"R1": [_sample_row(1, 2, "R1")]}
        with _make_reader(
            "aryx_ws_test_typecache_ttl", etype_rows, rtype_rows, row_map
        ) as (reader, mock_graph, calls):
            reader.subgraph(rel_limit=100)
            # Simulate the longer TTL elapsing without waiting in real time.
            key = mock_graph.name
            ts, et, rt = reader_mod._types_cache[key]
            reader_mod._types_cache[key] = (ts - reader_mod._TYPES_TTL - 1, et, rt)
            reader_mod._subgraph_cache.clear()  # force a real subgraph() miss too

            reader.subgraph(rel_limit=100)

        distinct_calls = [c for c in calls if "DISTINCT" in c[0]]
        assert len(distinct_calls) == 4, "types cache must refresh once expired"


class TestPerRelationshipTypeFanOut:
    def setup_method(self):
        reader_mod._types_cache.clear()
        reader_mod._subgraph_cache.clear()

    def test_every_relationship_type_is_still_queried_and_included(self):
        """Parallelizing step 2 must not drop or duplicate any relationship
        type's contribution to the result."""
        rel_types = [f"R{i}" for i in range(12)]
        etype_rows = [["TypeA"]]
        rtype_rows = [[r] for r in rel_types]
        row_map = {r: [_sample_row(i, i + 100, r)] for i, r in enumerate(rel_types)}
        with _make_reader(
            "aryx_ws_test_fanout", etype_rows, rtype_rows, row_map
        ) as (reader, mock_graph, calls):
            result = reader.subgraph(rel_limit=2000)

        rel_names_seen = {rel["name"] for rel in result["relationships"]}
        assert rel_names_seen == set(rel_types)

        sampler_calls = [c for c in calls if "r:REL {name: $rname}" in c[0]]
        assert len(sampler_calls) == len(rel_types), (
            "each relationship type must be queried exactly once, not "
            f"{len(sampler_calls)} times for {len(rel_types)} types"
        )

    def test_workers_use_independent_connections_not_the_callers_graph_handle(self):
        """The whole point of fanning out is concurrency -- which is only
        safe if each worker has its own connection. Assert _new_connection
        is actually invoked (i.e. the fan-out path doesn't quietly fall
        back to reusing self._graph across threads)."""
        rel_types = [f"R{i}" for i in range(5)]
        etype_rows = [["TypeA"]]
        rtype_rows = [[r] for r in rel_types]
        row_map = {r: [_sample_row(i, i + 100, r)] for i, r in enumerate(rel_types)}
        with _make_reader(
            "aryx_ws_test_conn_isolation", etype_rows, rtype_rows, row_map
        ) as (reader, mock_graph, _calls):
            seen_calls = []
            real_new_conn = reader._new_connection

            def _spy():
                seen_calls.append(1)
                return real_new_conn()

            reader._new_connection = _spy
            reader.subgraph(rel_limit=2000)

        assert len(seen_calls) == len(rel_types)

    def test_no_relationship_types_skips_the_pool_without_erroring(self):
        """Regression guard: ThreadPoolExecutor(max_workers=0) raises. A
        workspace with entities but zero relationships must not crash."""
        etype_rows = [["TypeA"]]
        with _make_reader(
            "aryx_ws_test_no_rels", etype_rows, [], {}
        ) as (reader, _mock_graph, _calls):
            result = reader.subgraph(rel_limit=2000)

        assert result["relationships"] == []
