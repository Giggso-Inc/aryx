"""Tier-0 deterministic co-occurrence linking for document-derived entities.

Real incident: a 97-type PDF batch ended with 63% of its entities isolated
even after FK detection, dimension-hub linking, and the LLM safety net all
ran successfully — none of those signals exist for free text (no shared
columns, no exact value matches). But entities extracted from the SAME
document chunk (the same passage the extractor saw in one call) are a real,
cheap, structural signal none of the other tiers use at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.pipeline.cooccurrence_link import _chunk_groups, detect_and_link_cooccurrence


def _settings(**overrides):
    defaults = dict(
        cooccurrence_link_enabled=True,
        cooccurrence_max_pairs_per_chunk=200,
    )
    defaults.update(overrides)
    return type("S", (), defaults)()


def _store(entities):
    store = MagicMock()
    store.list_entities.return_value = entities
    return store


def test_chunk_groups_groups_by_doc_and_chunk():
    entities = [
        (1, "Metric", {"doc_id": "d1", "chunk_index": 0}),
        (2, "Goal", {"doc_id": "d1", "chunk_index": 0}),
        (3, "Metric", {"doc_id": "d1", "chunk_index": 1}),
    ]
    groups = _chunk_groups(entities)
    assert groups[("d1", 0)] == [1, 2]
    assert groups[("d1", 1)] == [3]


def test_chunk_groups_never_merges_different_documents_sharing_a_chunk_index():
    """The exact latent bug this fix closes: two unrelated PDFs in the same
    workspace both have a "chunk 0" — grouping by chunk_index alone would
    wrongly link entities from completely different documents."""
    entities = [
        (1, "Metric", {"doc_id": "doc-A", "chunk_index": 0}),
        (2, "Goal", {"doc_id": "doc-B", "chunk_index": 0}),
    ]
    groups = _chunk_groups(entities)
    assert groups[("doc-A", 0)] == [1]
    assert groups[("doc-B", 0)] == [2]
    assert ("doc-A", 0) != ("doc-B", 0)


def test_chunk_groups_skips_entities_without_doc_or_chunk_attrs():
    """Tabular/XML entities never carry these attributes — must be a no-op,
    not an error."""
    entities = [
        (1, "Customer", {"name": "Acme"}),
        (2, "Metric", {"doc_id": "d1", "chunk_index": 0}),
    ]
    groups = _chunk_groups(entities)
    assert list(groups.values()) == [[2]]


def test_detect_and_link_cooccurrence_links_same_chunk_entities():
    entities = [
        (1, "Metric", {"doc_id": "d1", "chunk_index": 0}),
        (2, "Goal", {"doc_id": "d1", "chunk_index": 0}),
        (3, "Strategy", {"doc_id": "d1", "chunk_index": 0}),
        (4, "Metric", {"doc_id": "d1", "chunk_index": 5}),
    ]
    store = _store(entities)
    with patch("aryx.pipeline.cooccurrence_link.get_settings", return_value=_settings()):
        edges = detect_and_link_cooccurrence(store)

    assert edges == 3  # C(3,2) pairs within chunk 0; entity 4 alone in its chunk
    store.save_relationships.assert_called_once()
    saved = store.save_relationships.call_args[0][0]
    assert all(r.name == "mentioned_with" for r in saved)
    assert all(r.confidence == 0.5 for r in saved)
    linked_ids = {frozenset((r.source_entity_id, r.target_entity_id)) for r in saved}
    assert linked_ids == {frozenset((1, 2)), frozenset((1, 3)), frozenset((2, 3))}


def test_detect_and_link_cooccurrence_noop_when_disabled():
    store = _store([
        (1, "Metric", {"doc_id": "d1", "chunk_index": 0}),
        (2, "Goal", {"doc_id": "d1", "chunk_index": 0}),
    ])
    with patch("aryx.pipeline.cooccurrence_link.get_settings",
               return_value=_settings(cooccurrence_link_enabled=False)):
        assert detect_and_link_cooccurrence(store) == 0
    store.save_relationships.assert_not_called()


def test_detect_and_link_cooccurrence_noop_on_no_entities():
    store = _store([])
    with patch("aryx.pipeline.cooccurrence_link.get_settings", return_value=_settings()):
        assert detect_and_link_cooccurrence(store) == 0


def test_detect_and_link_cooccurrence_noop_for_tabular_only_workspace():
    """No entity carries doc_id/chunk_index — must be a clean no-op, not an
    error, for a workspace with only spreadsheet-derived data."""
    store = _store([
        (1, "Customer", {"name": "Acme"}),
        (2, "Order", {"amount": "10"}),
    ])
    with patch("aryx.pipeline.cooccurrence_link.get_settings", return_value=_settings()):
        assert detect_and_link_cooccurrence(store) == 0
    store.save_relationships.assert_not_called()


def test_detect_and_link_cooccurrence_caps_pairs_per_chunk():
    entities = [(i, "Metric", {"doc_id": "d1", "chunk_index": 0}) for i in range(1, 6)]  # C(5,2)=10 pairs
    store = _store(entities)
    with patch("aryx.pipeline.cooccurrence_link.get_settings",
               return_value=_settings(cooccurrence_max_pairs_per_chunk=3)):
        edges = detect_and_link_cooccurrence(store)
    assert edges == 3
