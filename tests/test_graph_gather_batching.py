"""docs/FALKORDB_QUERY_EXHAUSTION_2026_08_14.md -- gather() batches its
neighbor lookups via GraphReader.neighbors_batch() instead of calling
neighbors() once per matched entity, collapsing the dominant N+1 on the
/ask retrieval path into one call per request.
"""
from __future__ import annotations

from aryx.graph.retrieve import gather


class _FakeReader:
    """Minimal GraphReader double -- gather() only calls these four methods."""

    def __init__(self, entities_by_term, neighbor_map, provenance_map):
        self._entities_by_term = entities_by_term
        self._neighbor_map = neighbor_map
        self._provenance_map = provenance_map
        self.neighbors_batch_calls: list[list[int]] = []
        self.neighbors_calls: list[int] = []
        self.provenance_calls: list[int] = []

    def get_entity(self, entity_id):
        return None

    def find_entities(self, name=None, limit=5):
        return self._entities_by_term.get(name, [])

    def neighbors_batch(self, entity_ids):
        self.neighbors_batch_calls.append(list(entity_ids))
        return {eid: self._neighbor_map.get(eid, []) for eid in entity_ids
                if eid in self._neighbor_map}

    def neighbors(self, entity_id):
        # Present so a regression to the old per-entity call path would
        # still run (and be caught by the "not called" assertions below)
        # rather than crashing outright.
        self.neighbors_calls.append(entity_id)
        return self._neighbor_map.get(entity_id, [])

    def provenance(self, entity_id):
        self.provenance_calls.append(entity_id)
        return self._provenance_map.get(entity_id, [])


def test_gather_issues_one_batched_neighbors_call_for_all_hits():
    reader = _FakeReader(
        entities_by_term={
            "alpha": [{"id": 1, "type": "T", "name": "A1"},
                      {"id": 2, "type": "T", "name": "A2"}],
            "beta": [{"id": 3, "type": "T", "name": "B1"}],
        },
        neighbor_map={1: [{"id": 10}], 2: [{"id": 20}], 3: [{"id": 30}]},
        provenance_map={},
    )

    entities, calls = gather(reader, ["alpha", "beta"])

    assert reader.neighbors_calls == []
    assert len(reader.neighbors_batch_calls) == 1
    assert sorted(reader.neighbors_batch_calls[0]) == [1, 2, 3]
    assert sum(1 for c in calls if c.startswith("get_neighbors_batch(")) == 1
    assert sum(1 for c in calls if c.startswith("get_neighbors(")) == 0


def test_gather_still_fetches_provenance_per_entity():
    reader = _FakeReader(
        entities_by_term={"alpha": [{"id": 1, "type": "T", "name": "A1"}]},
        neighbor_map={},
        provenance_map={1: [{"system": "s", "dataset": "d"}]},
    )

    entities, calls = gather(reader, ["alpha"])

    assert reader.provenance_calls == [1]
    assert "get_provenance(1)" in calls


def test_gather_maps_batched_neighbors_back_to_the_right_entity():
    reader = _FakeReader(
        entities_by_term={
            "alpha": [{"id": 1, "type": "T", "name": "A1"}],
            "beta": [{"id": 2, "type": "T", "name": "B1"}],
        },
        neighbor_map={1: [{"id": 10, "type": "N", "name": "n1"}],
                      2: [{"id": 20, "type": "N", "name": "n2"}]},
        provenance_map={},
    )

    entities, _ = gather(reader, ["alpha", "beta"])

    by_id = {e.id: e for e in entities}
    assert [n["id"] for n in by_id[1].neighbors] == [10]
    assert [n["id"] for n in by_id[2].neighbors] == [20]


def test_gather_with_no_hits_never_calls_neighbors_batch():
    reader = _FakeReader(entities_by_term={}, neighbor_map={}, provenance_map={})

    entities, calls = gather(reader, ["nothing"])

    assert entities == []
    assert reader.neighbors_batch_calls == []
    assert not any(c.startswith("get_neighbors_batch(") for c in calls)


def test_gather_deduplicates_entities_seen_across_terms():
    reader = _FakeReader(
        entities_by_term={
            "alpha": [{"id": 1, "type": "T", "name": "A1"}],
            "beta": [{"id": 1, "type": "T", "name": "A1"}],
        },
        neighbor_map={1: [{"id": 10}]},
        provenance_map={},
    )

    entities, _ = gather(reader, ["alpha", "beta"])

    assert len(entities) == 1
    assert reader.neighbors_batch_calls == [[1]]
