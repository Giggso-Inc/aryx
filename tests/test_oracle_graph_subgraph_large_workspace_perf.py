"""Oracle-backend counterpart to test_graph_subgraph_large_workspace_perf.py.

docs/GRAPH_SUBGRAPH_LARGE_WORKSPACE_PERFORMANCE_2026_09_02.md's fix
(dev-rv-msi #316, ported to dev_oci 2026-09-10) only covered
GraphReader.subgraph() (FalkorDB) -- confirmed via investigation that
OracleGraphReader.subgraph() (used whenever ARYX_OCI_MODE=true /
ARYX_GRAPH_BACKEND=oci_graph, see ports/container.py) has the identical
performance shape: a full-scan relationship-type discovery query, then
one sequential per-relationship-type sample query per type -- and,
unlike FalkorDB, aryx_graph_edge had NO index at all covering
(workspace_id, name) before this pass. Same class of fix ported here:
a longer-TTL type-discovery cache, a small worker-pool fan-out for the
per-type queries (each on its own pooled connection), and a
result-level cache mirroring GraphReader's own _subgraph_cache (which
Oracle's subgraph() previously had no equivalent of at all).
"""
from __future__ import annotations

import contextlib
import threading
from unittest.mock import MagicMock, patch

import aryx.graph.oracle_graph_reader_traverse as traverse_mod
from aryx.graph.oracle_graph_reader import OracleGraphReader


def _sample_row(a_id, b_id, rname):
    return [a_id, "TypeA", f"a{a_id}", {}, b_id, "TypeB", f"b{b_id}", {}, rname]


@contextlib.contextmanager
def _make_reader(workspace_id: int, rtype_rows, rtype_row_map, vertex_rows=None):
    """Build an OracleGraphReader against a mocked pool, routing each
    cursor.execute() call by SQL shape:

      - `DISTINCT name FROM aryx_graph_edge` -> rtype_rows
      - the per-relationship-type sampler (`e.name = :rel`) -> rtype_row_map[rname]
      - the isolated-entity fill (`FROM aryx_graph_vertex`) -> vertex_rows or []

    subgraph() opens fresh connections per fan-out worker via
    self._connection() -> self._pool.connection(), so the pool mock must
    stay active for the whole subgraph() call, not just __init__.
    """
    call_log: list[tuple] = []
    lock = threading.Lock()

    def _make_cursor():
        cur = MagicMock()

        def _execute(sql, params=None):
            with lock:
                call_log.append((sql, params or {}, threading.get_ident()))
            cur._sql = sql
            cur._params = params or {}

        def _fetchall():
            sql, params = cur._sql, cur._params
            if "DISTINCT name" in sql:
                return rtype_rows
            if "e.name = :rel" in sql:
                return rtype_row_map.get(params.get("rel"), [])
            if "FROM aryx_graph_vertex" in sql:
                return vertex_rows or []
            return []

        cur.execute.side_effect = _execute
        cur.fetchall.side_effect = _fetchall
        return cur

    def _connection_ctx():
        conn = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = conn
        cm.__exit__.return_value = False
        cursor_cm = MagicMock()
        cursor_cm.__enter__.side_effect = lambda: _make_cursor()
        cursor_cm.__exit__.return_value = False
        conn.cursor.return_value = cursor_cm
        return cm

    mock_pool = MagicMock()
    mock_pool.connection.side_effect = lambda: _connection_ctx()

    with patch("aryx.store.oracle_pool.get_oracle_pool", return_value=mock_pool):
        reader = OracleGraphReader("tcps://test:1522/db", workspace_id=workspace_id)
        yield reader, call_log


class TestOracleTypeDiscoveryCache:
    def setup_method(self):
        traverse_mod._types_cache.clear()
        traverse_mod._subgraph_cache.clear()

    def test_second_call_with_different_rel_limit_skips_the_distinct_scan(self):
        """Two subgraph() calls with different rel_limit are separate entries
        in _subgraph_cache (cache miss both times), but must share one
        _types_cache entry -- the expensive DISTINCT scan runs once, not
        twice."""
        rtype_rows = [["R1"]]
        row_map = {"R1": [_sample_row(1, 2, "R1")]}
        with _make_reader(101, rtype_rows, row_map) as (reader, calls):
            reader.subgraph(rel_limit=100)
            reader.subgraph(rel_limit=200)  # different cache_key -> real miss

        distinct_calls = [c for c in calls if "DISTINCT" in c[0]]
        assert len(distinct_calls) == 1, (
            "expected exactly one relationship-type discovery scan total, "
            f"got {len(distinct_calls)}"
        )

    def test_types_cache_expires_after_its_own_longer_ttl(self):
        rtype_rows = [["R1"]]
        row_map = {"R1": [_sample_row(1, 2, "R1")]}
        with _make_reader(102, rtype_rows, row_map) as (reader, calls):
            reader.subgraph(rel_limit=100)
            key = reader.graph_name
            ts, rt = traverse_mod._types_cache[key]
            traverse_mod._types_cache[key] = (ts - traverse_mod._TYPES_TTL - 1, rt)
            traverse_mod._subgraph_cache.clear()  # force a real subgraph() miss too

            reader.subgraph(rel_limit=100)

        distinct_calls = [c for c in calls if "DISTINCT" in c[0]]
        assert len(distinct_calls) == 2, "types cache must refresh once expired"

    def test_subgraph_result_itself_is_cached(self):
        """Repeated calls with the SAME rel_limit must hit _subgraph_cache
        and not re-run the per-type sampler at all."""
        rtype_rows = [["R1"]]
        row_map = {"R1": [_sample_row(1, 2, "R1")]}
        with _make_reader(103, rtype_rows, row_map) as (reader, calls):
            reader.subgraph(rel_limit=100)
            reader.subgraph(rel_limit=100)

        sampler_calls = [c for c in calls if "e.name = :rel" in c[0]]
        assert len(sampler_calls) == 1, "second identical call must be a pure cache hit"


class TestOraclePerRelationshipTypeFanOut:
    def setup_method(self):
        traverse_mod._types_cache.clear()
        traverse_mod._subgraph_cache.clear()

    def test_every_relationship_type_is_still_queried_and_included(self):
        """Parallelizing step 2 must not drop or duplicate any relationship
        type's contribution to the result."""
        rel_types = [f"R{i}" for i in range(12)]
        rtype_rows = [[r] for r in rel_types]
        row_map = {r: [_sample_row(i, i + 100, r)] for i, r in enumerate(rel_types)}
        with _make_reader(104, rtype_rows, row_map) as (reader, calls):
            result = reader.subgraph(rel_limit=2000)

        rel_names_seen = {rel["name"] for rel in result["relationships"]}
        assert rel_names_seen == set(rel_types)

        sampler_calls = [c for c in calls if "e.name = :rel" in c[0]]
        assert len(sampler_calls) == len(rel_types), (
            "each relationship type must be queried exactly once, not "
            f"{len(sampler_calls)} times for {len(rel_types)} types"
        )

    def test_workers_use_independent_pooled_connections(self):
        """The whole point of fanning out is concurrency -- which is only
        safe if each worker borrows its own connection from the pool.
        Assert the pool's connection() factory is actually invoked once
        per relationship type (i.e. the fan-out path doesn't quietly
        reuse a single connection across threads)."""
        rel_types = [f"R{i}" for i in range(5)]
        rtype_rows = [[r] for r in rel_types]
        row_map = {r: [_sample_row(i, i + 100, r)] for i, r in enumerate(rel_types)}
        with _make_reader(105, rtype_rows, row_map) as (reader, _calls):
            reader.subgraph(rel_limit=2000)
            # 1 call for the type-discovery scan + 1 per relationship type
            # sampler + 1 for the isolated-entity fill (remaining == 0 here
            # since every entity already has a rel, so no 3rd call in this
            # case) -- assert at least one connection per relationship type.
            assert reader._pool.connection.call_count >= len(rel_types)

    def test_no_relationship_types_skips_the_pool_without_erroring(self):
        """Regression guard: ThreadPoolExecutor(max_workers=0) raises. A
        workspace with entities but zero relationships must not crash."""
        with _make_reader(106, [], {}, vertex_rows=[[1, "TypeA", "a1", {}]]) as (reader, _calls):
            result = reader.subgraph(rel_limit=2000)

        assert result["relationships"] == []
