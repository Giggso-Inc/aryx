"""Tier-2 deterministic dimension-hub linking.

Real incident: a 300K-row disposition-report table had no usable row-level
key — dynamic_fk.py correctly rejected every FK candidate against it as
non-selective (a real, logged example: State column, 100% value overlap
with another table, REJECTED for exceeding max estimated fanout) — and
stayed 100% isolated in the graph even though it shared an obvious
real-world dimension (state, FSC group) with other ingested tables. This
module makes the opposite use of the same "shared low-cardinality column"
signal that dynamic_fk.py rejects for FK purposes: instead of a row-to-row
edge, it links every row sharing a value to one small hub entity for that
value.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.pipeline.dimension_link import (
    _candidate_columns,
    _dimension_groups,
    _is_dimension_column,
    detect_and_link_dimensions,
)


def _settings(**overrides):
    defaults = dict(
        dimension_link_enabled=True,
        dimension_min_distinct_values=2,
        dimension_max_cardinality_ratio=0.5,
        dimension_min_overlap=0.5,
        dimension_min_types=2,
        max_relationships_per_fk_spec=10_000,
    )
    defaults.update(overrides)
    return type("S", (), defaults)()


def test_is_dimension_column_rejects_below_min_distinct():
    assert _is_dimension_column({"a": [1]}, total_rows=10, min_distinct=2,
                                 max_cardinality_ratio=0.5) is False


def test_is_dimension_column_rejects_high_cardinality():
    value_map = {str(i): [i] for i in range(9)}  # 9 distinct out of 10 rows
    assert _is_dimension_column(value_map, total_rows=10, min_distinct=2,
                                 max_cardinality_ratio=0.5) is False


def test_is_dimension_column_accepts_low_cardinality_repeated_column():
    value_map = {"pa": [1, 2, 3], "ca": [4, 5]}  # 2 distinct out of 5 rows
    assert _is_dimension_column(value_map, total_rows=5, min_distinct=2,
                                 max_cardinality_ratio=0.5) is True


def test_candidate_columns_groups_by_type_column_value():
    entities = [
        (1, "Surplus", {"State": "PA", "FSC": "84"}),
        (2, "Surplus", {"State": "CA", "FSC": "84"}),
        (3, "WashPost", {"State": "PA"}),
    ]
    grouped = _candidate_columns(entities)
    assert grouped["Surplus"]["State"] == {"pa": [1], "ca": [2]}
    assert grouped["WashPost"]["State"] == {"pa": [3]}


def test_candidate_columns_skips_internal_and_empty_fields():
    entities = [(1, "T", {"_ontology_type": "T", "name": "", "State": "PA"})]
    grouped = _candidate_columns(entities)
    assert "_ontology_type" not in grouped["T"]
    assert "name" not in grouped["T"]
    assert grouped["T"]["State"] == {"pa": [1]}


def test_dimension_groups_clusters_overlapping_columns_across_types():
    candidates = {
        ("Surplus", "State"): {"pa": [1], "ca": [2]},
        ("WashPost", "State"): {"pa": [3], "ca": [4]},
        ("Scrap", "Region"): {"west": [5]},  # no overlap with State values
    }
    groups = _dimension_groups(candidates, min_overlap=0.5, min_types=2)
    assert len(groups) == 1
    assert set(groups[0]) == {("Surplus", "State"), ("WashPost", "State")}


def test_dimension_groups_never_clusters_within_the_same_type():
    """Two columns of the SAME type sharing values (e.g. two date fields)
    must not form a 'dimension group' — a dimension link only has value
    when it connects DIFFERENT entity types."""
    candidates = {
        ("Surplus", "State"): {"pa": [1]},
        ("Surplus", "Region"): {"pa": [1]},
    }
    groups = _dimension_groups(candidates, min_overlap=0.5, min_types=2)
    assert groups == []


def test_dimension_groups_min_types_1_allows_singleton_groups():
    """Two same-type columns never merge (across-type only), so each stays
    its own singleton group — which trivially satisfies min_types=1."""
    candidates = {
        ("Surplus", "State"): {"pa": [1]},
        ("Surplus", "Region"): {"pa": [1]},
    }
    groups = _dimension_groups(candidates, min_overlap=0.5, min_types=1)
    assert sorted(tuple(g) for g in groups) == [
        (("Surplus", "Region"),), (("Surplus", "State"),),
    ]


def _store(entities):
    store = MagicMock()
    store.list_entities.return_value = entities
    created_ids = iter(range(1000, 2000))
    store.create_entity.side_effect = lambda *a, **k: next(created_ids)
    return store


def test_detect_and_link_dimensions_links_the_surplus_style_case():
    """The exact real-world shape: a poorly-keyed type shares a low-cardinality
    State column with two other, better-keyed types — no row-level key
    anywhere, but a real shared dimension."""
    entities = [
        (1, "Surplus", {"State": "PA", "id_col": "s1"}),
        (2, "Surplus", {"State": "CA", "id_col": "s2"}),
        (3, "Surplus", {"State": "PA", "id_col": "s3"}),
        (4, "Surplus", {"State": "PA", "id_col": "s4"}),
        (5, "Surplus", {"State": "CA", "id_col": "s5"}),
        (6, "WashPost", {"State": "PA", "id_col": "w1"}),
        (7, "WashPost", {"State": "CA", "id_col": "w2"}),
        (8, "WashPost", {"State": "PA", "id_col": "w3"}),
        (9, "WashPost", {"State": "PA", "id_col": "w4"}),
        (10, "Scrap", {"State": "CA", "id_col": "c1"}),
        (11, "Scrap", {"State": "PA", "id_col": "c2"}),
        (12, "Scrap", {"State": "CA", "id_col": "c3"}),
        (13, "Scrap", {"State": "CA", "id_col": "c4"}),
    ]
    store = _store(entities)
    with patch("aryx.pipeline.dimension_link.get_settings", return_value=_settings()):
        edges = detect_and_link_dimensions(store)

    assert edges > 0
    store.create_entity.assert_called()
    # Every created hub is under a Dimension: type, confidence 0.5 (weak, not a real FK).
    for call in store.create_entity.call_args_list:
        ontology_type = call.args[0]
        assert ontology_type.startswith("Dimension:")
        assert call.kwargs.get("confidence") == 0.5
    store.save_relationships.assert_called_once()
    saved = store.save_relationships.call_args[0][0]
    assert all(r.confidence == 0.5 for r in saved)
    assert all(r.name.startswith("has_") for r in saved)
    # Entity 1 (Surplus/PA) and entity 6 (WashPost/PA) must land on the SAME hub.
    pa_ids = {r.target_entity_id for r in saved if r.source_entity_id in (1, 6)}
    assert len(pa_ids) == 1


def test_detect_and_link_dimensions_noop_when_disabled():
    store = _store([(1, "Surplus", {"State": "PA"}), (2, "WashPost", {"State": "PA"})])
    with patch("aryx.pipeline.dimension_link.get_settings",
               return_value=_settings(dimension_link_enabled=False)):
        assert detect_and_link_dimensions(store) == 0
    store.create_entity.assert_not_called()


def test_detect_and_link_dimensions_noop_on_no_entities():
    store = _store([])
    with patch("aryx.pipeline.dimension_link.get_settings", return_value=_settings()):
        assert detect_and_link_dimensions(store) == 0


def test_detect_and_link_dimensions_noop_when_no_shared_dimension_exists():
    """Two types with only high-cardinality (near-unique) columns — nothing
    for Tier 2 to do; Tier 1 (dynamic_fk) would be the right mechanism if
    they were actually selective enough to be a real key."""
    entities = [
        (1, "A", {"unique_id": "a1"}),
        (2, "A", {"unique_id": "a2"}),
        (3, "B", {"unique_id": "b1"}),
        (4, "B", {"unique_id": "b2"}),
    ]
    store = _store(entities)
    with patch("aryx.pipeline.dimension_link.get_settings",
               return_value=_settings(dimension_max_cardinality_ratio=0.1)):
        assert detect_and_link_dimensions(store) == 0
    store.create_entity.assert_not_called()


def test_detect_and_link_dimensions_caps_edges_per_dimension_group():
    """Consistent with fk_edges.py's max_relationships_per_fk_spec guard —
    but weak/best-effort: save what was collected instead of aborting."""
    entities = [(i, "Surplus", {"State": "PA"}) for i in range(1, 6)]
    entities += [(50, "Surplus", {"State": "CA"})]
    entities += [
        (100, "WashPost", {"State": "PA"}), (101, "WashPost", {"State": "PA"}),
        (102, "WashPost", {"State": "CA"}), (103, "WashPost", {"State": "PA"}),
    ]
    store = _store(entities)
    with patch("aryx.pipeline.dimension_link.get_settings",
               return_value=_settings(max_relationships_per_fk_spec=2)):
        edges = detect_and_link_dimensions(store)
    assert edges == 2
    store.save_relationships.assert_called_once()
    assert len(store.save_relationships.call_args[0][0]) == 2
