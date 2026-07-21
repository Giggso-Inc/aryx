"""fetch_attr_set_assoc (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md): reads
BigMachines' composite "array set" definitions (bm_config_attr_set +
bm_config_attr_set_assoc) — both fetched via the existing, dialect-agnostic
fetch_entities_by_type, so this single implementation on PostgresCpqRdb
serves Oracle too through inheritance (same pattern as fetch_function_scripts).
"""
from __future__ import annotations

from aryx.cpq.rdb import PostgresCpqRdb


def _rdb(monkeypatch, set_rows, assoc_rows):
    rdb = PostgresCpqRdb()

    def _fake_fetch(workspace_id, type_suffix, catalog_prefix=""):
        if type_suffix == "bmconfigattrset":
            return [(i, r) for i, r in enumerate(set_rows, start=1)]
        if type_suffix == "bmconfigattrsetassoc":
            return [(i, r) for i, r in enumerate(assoc_rows, start=1)]
        return []

    monkeypatch.setattr(rdb, "fetch_entities_by_type", _fake_fetch)
    return rdb


def test_fetch_attr_set_assoc_returns_ordered_member_columns(monkeypatch):
    set_rows = [
        {"id": "19435423713", "variable_name": "mountingTypeArrayset_viSoln",
         "size_attr_id": "19435423551", "default_attr_id": "-1"},
    ]
    assoc_rows = [
        {"set_id": "19435423713", "attr_id": "19435423615", "display_order_number": "2"},
        {"set_id": "19435423713", "attr_id": "19435423613", "display_order_number": "1"},
        {"set_id": "19435423713", "attr_id": "19435423627", "display_order_number": "3"},
    ]
    rdb = _rdb(monkeypatch, set_rows, assoc_rows)

    result = rdb.fetch_attr_set_assoc(workspace_id=19)

    assert 19435423713 in result
    sdef = result[19435423713]
    assert sdef["driver_attr_id"] == 19435423551
    assert sdef["variable_name"] == "mountingTypeArrayset_viSoln"
    assert sdef["members"] == [
        (19435423613, 1), (19435423615, 2), (19435423627, 3),
    ], "members must be ordered by display_order_number, not fetch order"


def test_fetch_attr_set_assoc_skips_trivial_self_wrap_sets(monkeypatch):
    # Most bm_config_attr_set rows are 1-attribute self-wraps with
    # size_attr_id=-1 — NOT real array-sets (docs/CPQ_RULE_TOOL_FLOW_PLAN.md
    # §15c) — must not appear in the result at all.
    set_rows = [
        {"id": "1", "variable_name": "promotionId", "size_attr_id": "-1"},
        {"id": "2", "variable_name": "realSet_viSoln", "size_attr_id": "500"},
    ]
    rdb = _rdb(monkeypatch, set_rows, [])

    result = rdb.fetch_attr_set_assoc(workspace_id=19)

    assert 1 not in result
    assert 2 in result


def test_fetch_attr_set_assoc_ignores_assoc_rows_for_unknown_sets(monkeypatch):
    assoc_rows = [{"set_id": "999", "attr_id": "1", "display_order_number": "1"}]
    rdb = _rdb(monkeypatch, [], assoc_rows)

    result = rdb.fetch_attr_set_assoc(workspace_id=19)

    assert result == {}
