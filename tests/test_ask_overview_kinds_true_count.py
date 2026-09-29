"""ask_overview._kinds() must report the TRUE per-type count, not a
len(find_entities(limit=500))-capped scan, and must do it in one query.

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: on a workspace with more than
500 entities, the old scan could both miss types entirely and under-count
the ones it did see, depending on insertion/return order.

T11 follow-up (real-data testing against workspace 704, 2026-09-25): the
first fix (distinct_types() + count_entities(t) + find_entities(...) once
per type) was correct but measured at ~276s against a 109-type/204k-entity
real workspace, since build() runs on every non-quote /ask turn.
type_overview() replaces that loop with a single grouped query; these tests
cover the new call shape.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.api.ask_overview import _kinds


def _reader(overview):
    reader = MagicMock()
    reader.type_overview.return_value = overview
    return reader


def test_kinds_reports_true_count_beyond_the_old_500_cap():
    reader = _reader({"Widget": {"count": 12000, "samples": ["Alpha", "Beta", "Gamma", "Delta"]}})
    lines = _kinds(reader)
    assert any("Widget: 12000 records" in line for line in lines)


def test_kinds_includes_every_type_type_overview_returns():
    """type_overview() is a single grouped query -- every type it returns
    must show up, regardless of relative record volume."""
    reader = _reader({
        "RareType": {"count": 3, "samples": ["only-one"]},
        "CommonType": {"count": 50000, "samples": ["x", "y", "z"]},
    })
    lines = _kinds(reader)
    assert any("RareType: 3 records" in line for line in lines)
    assert any("CommonType: 50000 records" in line for line in lines)


def test_kinds_calls_type_overview_with_sample_limit_three_not_a_per_type_loop():
    reader = _reader({"Widget": {"count": 10, "samples": ["A", "B", "C"]}})
    _kinds(reader)
    reader.type_overview.assert_called_once_with(sample_limit=3)
    reader.find_entities.assert_not_called()
    reader.distinct_types.assert_not_called()
    reader.count_entities.assert_not_called()


def test_kinds_returns_empty_list_on_no_types():
    reader = _reader({})
    assert _kinds(reader) == []


def test_kinds_returns_empty_list_when_type_overview_raises():
    reader = MagicMock()
    reader.type_overview.side_effect = RuntimeError("boom")
    assert _kinds(reader) == []


def test_kinds_lines_are_sorted_by_type_name():
    reader = _reader({
        "Zebra": {"count": 1, "samples": []},
        "Alpha": {"count": 1, "samples": []},
    })
    lines = _kinds(reader)
    body = [line for line in lines if line != "Kinds tracked:"]
    assert body == sorted(body)
