"""ask_overview._kinds() must report the TRUE per-type count, not a
len(find_entities(limit=500))-capped scan.

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: on a workspace with more than
500 entities, the old scan could both miss types entirely and under-count
the ones it did see, depending on insertion/return order.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.api.ask_overview import _kinds


def _reader(types, counts, samples):
    reader = MagicMock()
    reader.distinct_types.return_value = types
    reader.count_entities.side_effect = lambda t: counts[t]
    reader.find_entities.side_effect = lambda ontology_type, limit: [
        {"name": n} for n in samples.get(ontology_type, [])
    ][:limit]
    return reader


def test_kinds_reports_true_count_beyond_the_old_500_cap():
    reader = _reader(
        types=["Widget"],
        counts={"Widget": 12000},
        samples={"Widget": ["Alpha", "Beta", "Gamma", "Delta"]},
    )
    lines = _kinds(reader)
    assert any("Widget: 12000 records" in line for line in lines)


def test_kinds_includes_a_type_with_zero_matching_entities_in_the_first_500():
    """distinct_types() must surface every type even if a type's rows would
    never have appeared in a capped 500-row scan."""
    reader = _reader(
        types=["RareType", "CommonType"],
        counts={"RareType": 3, "CommonType": 50000},
        samples={"RareType": ["only-one"], "CommonType": ["x", "y", "z"]},
    )
    lines = _kinds(reader)
    assert any("RareType: 3 records" in line for line in lines)
    assert any("CommonType: 50000 records" in line for line in lines)


def test_kinds_samples_capped_at_three_names():
    reader = _reader(
        types=["Widget"],
        counts={"Widget": 10},
        samples={"Widget": ["A", "B", "C", "D"]},
    )
    lines = _kinds(reader)
    widget_line = next(line for line in lines if "Widget" in line)
    assert "D" not in widget_line


def test_kinds_returns_empty_list_on_no_types():
    reader = _reader(types=[], counts={}, samples={})
    assert _kinds(reader) == []


def test_kinds_skips_a_type_whose_count_query_raises_but_keeps_others():
    reader = MagicMock()
    reader.distinct_types.return_value = ["Broken", "Fine"]

    def _count(t):
        if t == "Broken":
            raise RuntimeError("boom")
        return 5

    reader.count_entities.side_effect = _count
    reader.find_entities.side_effect = lambda ontology_type, limit: [{"name": "x"}]
    lines = _kinds(reader)
    assert not any("Broken" in line for line in lines)
    assert any("Fine: 5 records" in line for line in lines)
