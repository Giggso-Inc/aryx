"""G1+G5: chunked-path equivalence with resolve(), and kill-and-resume."""
from __future__ import annotations

from collections import defaultdict

import pytest
from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolution.chunked import _cluster_pass, resolve_chunked
from aryx.resolution.run import resolve


class InMemoryBackend:
    """Dict-backed ChunkBackend — exact protocol, no Postgres."""

    def __init__(self, records: list[ResolutionRecord]) -> None:
        self._records = {r.record_id: r for r in records}
        self.members: dict[str, list[int]] = defaultdict(list)
        self.done: set[str] = set()
        self.match_edges: list[tuple[int, int, float]] = []
        self.blocks_scored = 0
        self.load_records_calls = 0

    def has_keys(self, run_id: int) -> bool:
        return bool(self.members)

    def add_members(self, run_id: int, rows) -> None:
        for key, rid in rows:
            self.members[key].append(rid)

    def todo_blocks(self, run_id: int):
        for key in sorted(self.members):
            if key not in self.done:
                yield key

    def block_record_ids(self, run_id: int, key: str) -> list[int]:
        return self.members[key]

    def load_records(self, ids) -> list[ResolutionRecord]:
        self.load_records_calls += 1
        return [self._records[i] for i in ids]

    def add_edges(self, run_id: int, edges) -> None:
        self.match_edges.extend(edges)

    def mark_done(self, run_id: int, key: str) -> None:
        self.done.add(key)
        self.blocks_scored += 1

    def edges(self, run_id: int):
        return list(self.match_edges)


def _fixture(n_clusters: int = 20, size: int = 5) -> list[ResolutionRecord]:
    names = [f"unique{c:02d} fixture entity" for c in range(n_clusters)]
    records, rid = [], 0
    for name in names:
        for _ in range(size):
            records.append(ResolutionRecord(record_id=rid, text=name,
                                            payload={"name": name}))
            rid += 1
    return records


def _cluster_sets(results) -> set[frozenset]:
    return {frozenset(m.landed_record_id for m in members)
            for _, members in results}


def test_equivalence_with_in_memory_resolve() -> None:
    """Chunked and legacy paths produce identical cluster sets."""
    records = _fixture()
    broker = MagicMock()
    broker.embed.side_effect = RuntimeError("no embeddings")
    legacy = _cluster_sets(resolve(records, broker, "Thing"))
    backend = InMemoryBackend(records)
    chunked = _cluster_sets(list(resolve_chunked(
        1, records, [r.record_id for r in records], backend, "Thing")))
    assert chunked == legacy


def test_kill_and_resume_identical_clusters() -> None:
    """Abort after N blocks, resume, final clusters match uninterrupted."""
    records = _fixture()
    uninterrupted = InMemoryBackend(records)
    expected = _cluster_sets(list(resolve_chunked(
        1, records, [r.record_id for r in records], uninterrupted, "Thing")))

    crashing = InMemoryBackend(records)
    original = crashing.mark_done
    calls = {"n": 0}

    def dying_mark_done(run_id: int, key: str) -> None:
        calls["n"] += 1
        if calls["n"] == 10:
            raise RuntimeError("simulated crash")
        original(run_id, key)

    crashing.mark_done = dying_mark_done
    with pytest.raises(RuntimeError):
        list(resolve_chunked(1, records, [r.record_id for r in records],
                             crashing, "Thing"))
    crashing.mark_done = original  # process restarts
    resumed = _cluster_sets(list(resolve_chunked(
        1, records, [r.record_id for r in records], crashing, "Thing")))
    assert resumed == expected


def test_resume_skips_key_pass() -> None:
    """Second invocation never re-keys (has_keys guard)."""
    records = _fixture(5)
    backend = InMemoryBackend(records)
    list(resolve_chunked(1, records, [r.record_id for r in records],
                         backend, "Thing"))
    member_count = sum(len(v) for v in backend.members.values())
    list(resolve_chunked(1, records, [r.record_id for r in records],
                         backend, "Thing"))
    assert sum(len(v) for v in backend.members.values()) == member_count


def test_oversized_block_skipped_with_done_marker() -> None:
    """Blocks over MAX_BLOCK are skipped but still marked done."""
    records = _fixture(1, size=3)
    backend = InMemoryBackend(records)
    backend.add_members(1, [("prefix:huge", r.record_id)
                            for r in records] * 2000)
    list(resolve_chunked(1, records, [r.record_id for r in records],
                         backend, "Thing"))
    assert "prefix:huge" in backend.done


def test_cluster_pass_batches_record_loads_not_once_per_cluster() -> None:
    """Regression for a real incident: a table whose blocking keys were too
    low-cardinality (near-constant fields) produced one giant block that got
    skipped as oversized, leaving zero match edges — so all 308,104 records
    became their own singleton cluster, and a per-cluster load_records call
    turned that into 308,104 individual DB round-trips, silently stalling
    the job for hours. Record loading must be batched, bounded by
    CLUSTER_LOAD_BATCH, regardless of how many singleton clusters result."""
    from aryx.resolution.chunked import CLUSTER_LOAD_BATCH

    n = 12000
    records = [ResolutionRecord(record_id=i, text=f"unique{i:06d} widget",
                                payload={"name": f"unique{i:06d} widget"})
               for i in range(n)]
    backend = InMemoryBackend(records)
    # Force every record into ONE shared, oversized block (mirrors the real
    # incident: a near-constant field collapsing everything into one key
    # that then gets skipped) — no edges are ever produced, so every record
    # ends up its own singleton cluster.
    backend.add_members(1, [("prefix:shared", r.record_id) for r in records])

    results = list(resolve_chunked(1, records, [r.record_id for r in records],
                                   backend, "Thing"))

    assert len(results) == n  # every record its own singleton entity
    expected_calls = -(-n // CLUSTER_LOAD_BATCH)  # ceil division
    assert backend.load_records_calls == expected_calls, (
        f"expected {expected_calls} batched load_records call(s), got "
        f"{backend.load_records_calls} — record loading is not batched"
    )


# ── edges() streaming + er_max_edges_per_run cap ────────────────────────────
# Regression coverage for a real incident: a 308,104-record run produced
# 14,374,847 match edges (46x the record count) from scoring — materializing
# all of them (plus the cluster pass's own same-size pair_scores dict) as one
# in-memory list was enough memory pressure to crash the container mid-run,
# silently orphaning the job with no logged error.

def test_cluster_pass_stops_at_edge_cap_safe_degradation() -> None:
    """Beyond er_max_edges_per_run, remaining edges are not consumed — some
    pairs simply don't merge (safe degradation), never a crash or hang."""
    n = 20
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={})
               for i in range(n)]
    backend = InMemoryBackend(records)
    # A chain 0-1, 1-2, ..., 18-19 — if ALL edges were consumed, every
    # record would merge into ONE cluster of size 20.
    backend.match_edges = [(i, i + 1, 1.0) for i in range(n - 1)]

    with patch("aryx.resolution.chunked.get_settings") as mock_settings:
        mock_settings.return_value.er_max_edges_per_run = 3
        results = list(_cluster_pass(
            1, backend, [r.record_id for r in records], "Thing", None,
        ))

    # Only the first 3 edges (0-1, 1-2, 2-3) are consumed -> {0,1,2,3} merge
    # into one cluster of size 4; the rest remain singletons.
    cluster_sizes = sorted(len(members) for _, members in results)
    assert cluster_sizes[-1] == 4
    assert cluster_sizes.count(1) == n - 4
    assert sum(cluster_sizes) == n  # no record lost


def test_cluster_pass_no_degradation_when_under_the_cap() -> None:
    """When edge count is comfortably under the cap, clustering is
    unaffected — the cap must never change behavior for normal-sized runs."""
    n = 20
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={})
               for i in range(n)]
    backend = InMemoryBackend(records)
    backend.match_edges = [(i, i + 1, 1.0) for i in range(n - 1)]

    with patch("aryx.resolution.chunked.get_settings") as mock_settings:
        mock_settings.return_value.er_max_edges_per_run = 1_000_000
        results = list(_cluster_pass(
            1, backend, [r.record_id for r in records], "Thing", None,
        ))

    assert len(results) == 1  # the whole chain merges into one cluster
    assert len(results[0][1]) == n


def test_pg_chunk_backend_edges_uses_streaming_named_cursor() -> None:
    """edges() must use a named (server-side) cursor with a bounded itersize
    — NOT a single fetchall() — so it never materializes an unbounded result
    set client-side, regardless of how many match edges a run has."""
    from aryx.store.chunk_backend import PgChunkBackend

    fake_rows = [(1, 2, 0.95), (3, 4, 0.90)]
    mock_cursor = MagicMock()
    mock_cursor.__iter__.return_value = iter(fake_rows)
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = False

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cm
    mock_conn_cm = MagicMock()
    mock_conn_cm.__enter__.return_value = mock_conn
    mock_conn_cm.__exit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn_cm

    with patch("aryx.store.chunk_backend.get_pool", return_value=mock_pool), \
         patch("aryx.store.chunk_backend.load", return_value="SELECT ..."):
        backend = PgChunkBackend("postgresql://x", workspace_id=1)
        result = list(backend.edges(42))

    assert result == fake_rows
    # Cursor must be created WITH a name (server-side/streaming), not a
    # plain client-side cursor.
    _, kwargs = mock_conn.cursor.call_args
    assert kwargs.get("name") == "aryx_edges_42"
    assert mock_cursor.itersize == 10_000


# ── pair_scores partitioning (cluster_edges O(clusters x edges) fix) ───────
# Regression coverage for a third real incident: _materialize() ->
# cluster_edges() scans its ENTIRE pair_scores argument for every cluster.
# Passing the same run-wide dict to every one of ~106,000 clusters made
# total cost scale as clusters x edges instead of just edges.

def test_cluster_pass_gives_each_cluster_only_its_own_pair_scores() -> None:
    """Each cluster's _materialize() call must receive ONLY its own relevant
    pair_scores subset, not the full run-wide dict."""
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(4)]
    backend = InMemoryBackend(records)
    # Two independent pairs -> two independent clusters: {0,1} and {2,3}.
    backend.match_edges = [(0, 1, 1.0), (2, 3, 1.0)]

    seen_sizes = []
    import aryx.resolution.chunked as chunked_module
    original_materialize = chunked_module._materialize

    def spy_materialize(member_ids, by_id, pair_scores, ontology_type, policy):
        seen_sizes.append(len(pair_scores))
        return original_materialize(member_ids, by_id, pair_scores, ontology_type, policy)

    with patch("aryx.resolution.chunked._materialize", side_effect=spy_materialize):
        results = list(resolve_chunked(1, records, [r.record_id for r in records],
                                       backend, "Thing"))

    assert len(results) == 2  # two clusters of size 2 each
    # Each cluster must see only its OWN 1 edge — never both (2) — which is
    # what "partitioned once" vs "full dict every time" actually proves.
    assert sorted(seen_sizes) == [1, 1]
