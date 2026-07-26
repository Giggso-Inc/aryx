"""Ingestion-projection performance fixes.

docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md: the "Project" stage
(RDB -> FalkorDB rebuild) went from a few seconds to ~70 minutes on an
83k-entity workspace, live-confirmed as an unindexed `:Source` label
scan (O(n^2) MERGE cost) plus one Cypher round-trip per entity/provenance
row where relationships already batch via UNWIND. Severe enough that an
external timeout watchdog marked a genuinely-still-working ingestion job
"failed" mid-run, because the Project stage reported progress only once
at entry and once at exit.

Fixes: Source.record_id index in clear(); add_entities_batch /
add_provenance_batch (UNWIND, mirroring the existing
add_relationships_batch); on_progress threaded through project_graph,
scaled by real rows written.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aryx.graph.falkor_store import FalkorStore
from aryx.project import project_graph


class _FakeGraphHandle:
    """Records every query issued, standing in for FalkorDB's Graph object."""

    def __init__(self):
        self.queries: list[tuple[str, dict]] = []

    def query(self, cypher, params=None):
        self.queries.append((cypher, params or {}))
        return MagicMock(result_set=[])

    def delete(self):
        pass


@pytest.fixture()
def store():
    fs = FalkorStore.__new__(FalkorStore)  # bypass __init__'s real connection
    fs._graph = _FakeGraphHandle()
    fs._index_candidates = set()
    return fs


class TestSourceIndex:
    def test_clear_creates_source_record_id_index(self, store):
        store.clear()
        index_queries = [q for q, _p in store._graph.queries if "CREATE INDEX" in q]
        assert any("Source" in q and "record_id" in q for q in index_queries), (
            "clear() must index Source.record_id — the unindexed MERGE was "
            "the O(n^2) root cause of the 'slow after 90%' symptom"
        )

    def test_clear_still_creates_entity_id_index(self, store):
        """Regression guard: the new Source index must not replace the
        pre-existing Entity.id index fix."""
        store.clear()
        index_queries = [q for q, _p in store._graph.queries if "CREATE INDEX" in q]
        assert any("Entity" in q and ".id" in q for q in index_queries)

    def test_index_creation_failure_is_non_fatal(self, store):
        """Perf-only optimization — a failure here must never break ingestion."""
        def _raise(*a, **k):
            raise RuntimeError("index already exists or unsupported")
        store._graph.query = _raise
        store.clear()  # must not raise

    def test_clear_creates_rel_name_index(self, store):
        """Real incident: GraphReader.subgraph() (the /graph endpoint) issues
        one query per relationship name, filtering on r.name with no index —
        on a ~600K-node, ~1.2M-relationship workspace this full-scanned every
        relationship (~1095ms per query), and stacking ~20 of them in one
        request exceeded FalkorDB's TIMEOUT, producing a 500. Confirmed live:
        the same query dropped to ~3ms once this index existed."""
        store.clear()
        index_queries = [q for q, _p in store._graph.queries if "CREATE INDEX" in q]
        assert any("REL" in q and "name" in q for q in index_queries), (
            "clear() must index REL.name — the unindexed relationship-name "
            "filter was the root cause of /graph timing out on large graphs"
        )


class TestEntitiesBatch:
    def test_groups_rows_by_label_set_one_query_per_group(self, store):
        entities = [
            (1, "TypeA", {"name": "a1"}, [], None),
            (2, "TypeA", {"name": "a2"}, [], None),
            (3, "TypeB", {"name": "b1"}, ["Ancestor"], None),
        ]
        written = store.add_entities_batch(entities)

        assert written == 3
        unwind_queries = [q for q, _p in store._graph.queries if "UNWIND" in q]
        # Two distinct label-sets (TypeA alone, TypeB+Ancestor) -> 2 queries,
        # not 3 (one per row) and not 1 (labels can't be parameterized).
        assert len(unwind_queries) == 2

    def test_on_batch_callback_reports_running_total(self, store):
        entities = [(i, "T", {}, [], None) for i in range(5)]
        seen: list[int] = []
        store.add_entities_batch(entities, batch_size=2, on_batch=seen.append)

        assert seen == [2, 4, 5]

    def test_preserves_iri_when_present(self, store):
        store.add_entities_batch([(1, "T", {}, [], "https://aryx.local/entity/1/1")])
        _q, params = next(
            (q, p) for q, p in store._graph.queries if "UNWIND" in q)
        assert params["rows"][0]["iri"] == "https://aryx.local/entity/1/1"


class TestProvenanceBatch:
    def test_batches_via_unwind(self, store):
        rows = [(i, "xml", "file.xml", f"rec{i}") for i in range(1200)]
        written = store.add_provenance_batch(rows, batch_size=500)

        assert written == 1200
        unwind_queries = [q for q, _p in store._graph.queries if "UNWIND" in q]
        assert len(unwind_queries) == 3  # ceil(1200/500)

    def test_on_batch_callback_reports_running_total(self, store):
        rows = [(i, "xml", "file.xml", f"rec{i}") for i in range(5)]
        seen: list[int] = []
        store.add_provenance_batch(rows, batch_size=2, on_batch=seen.append)

        assert seen == [2, 4, 5]

    def test_query_shape_creates_source_then_links_entity(self, store):
        store.add_provenance_batch([(7, "xml", "file.xml", "rec7")])
        cypher, params = store._graph.queries[0]

        assert "MERGE (s:Source" in cypher
        assert "MERGE (e)-[:FROM]->(s)" in cypher
        assert params["rows"][0] == {"sys": "xml", "ds": "file.xml", "rid": "rec7", "id": 7}


class _FakeEntityStore:
    """Minimal store double for project_graph's read side."""

    def __init__(self, n_entities=10, n_provenance=10, n_rels=5):
        self._entities = [(i, "T", {"name": f"e{i}"}) for i in range(n_entities)]
        self._provenance = [(i, "xml", "f.xml", f"r{i}") for i in range(n_provenance)]
        self._rels = [(i, (i + 1) % n_entities, "REL") for i in range(n_rels)]

    def list_entities(self):
        return iter(self._entities)

    def list_members_provenance(self):
        return iter(self._provenance)

    def list_relationships(self):
        return iter(self._rels)


def test_project_graph_uses_batch_methods_when_available(store):
    result = project_graph(_FakeEntityStore(n_entities=50, n_provenance=50, n_rels=20), store)

    assert result == {"entities": 50, "provenance": 50, "relationships": 20}
    unwind_queries = [q for q, _p in store._graph.queries if "UNWIND" in q]
    assert unwind_queries, "batch methods (UNWIND) must be used, not per-row add_entity/add_provenance"


def test_project_graph_emits_scaled_sub_progress(store):
    """The fix for the timeout-watchdog false-failure (§5a): progress must
    move THROUGH the 90-95 window as rows are written, not just once at
    entry and once at exit."""
    events: list[tuple[str, int, str]] = []
    project_graph(
        _FakeEntityStore(n_entities=1000, n_provenance=1000, n_rels=10),
        store, on_progress=lambda stage, pct, detail: events.append((stage, pct, detail)),
        pct_range=(90, 95),
    )

    assert events, "on_progress must fire during a real projection"
    pcts = [p for _s, p, _d in events]
    assert all(90 <= p <= 95 for p in pcts)
    assert len(set(pcts)) > 1, (
        "progress must move across multiple distinct values within the "
        "window, not report the same single point for the whole stage"
    )
    assert max(pcts) == 95


def test_project_graph_without_on_progress_is_unaffected():
    """Backward compatible — omitting on_progress must not change behavior
    or raise."""
    fs = FalkorStore.__new__(FalkorStore)
    fs._graph = _FakeGraphHandle()
    fs._index_candidates = set()
    result = project_graph(_FakeEntityStore(n_entities=5, n_provenance=5, n_rels=2), fs)

    assert result == {"entities": 5, "provenance": 5, "relationships": 2}
