"""Port of aryxent PR 6 (rule scoping by catalog-node ancestry) behind
cpq_rule_scope_filter_enabled. Off by default; off/unresolved must be a no-op.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq import model_resolution as mr
from aryx.cpq import rule_scope
from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb
from aryx.cpq.rdb.rdb_postgres import PostgresCpqRdb
from aryx.cpq.state import ConstraintRule, HidingRule, RecommendationRule, ValidationRule


def _cfg(on: bool):
    m = MagicMock()
    m.return_value.cpq_rule_scope_filter_enabled = on
    return m


def _rdb(cls, rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    obj = cls.__new__(cls)

    @contextmanager
    def _c():
        yield conn

    obj._connection = _c
    return obj, cur


def _bind(scope, resolved=True):
    chosen = mr.ModelCandidate(
        cpq_model="M1", display_names=frozenset(), node_name="n", node_id="10",
        base_models=frozenset(), match="exact", is_upgrade=False,
        soft_deleted=False,
    ) if resolved else None
    res = mr.ModelResolution(
        chosen=chosen, alternatives=(), deciding_step="x",
        source="hint" if resolved else "unresolved", scope_node_ids=frozenset(scope),
    )
    mr.bind_turn(mr.TurnModelContext(resolution=res, workspace_id=1, catalog_prefix=""))


@pytest.fixture(autouse=True)
def _unbind():
    mr.bind_turn(None)
    yield
    mr.bind_turn(None)


def _rules():
    return [
        HidingRule("in", 0, "", 1, ref_id="10"),
        HidingRule("anc", 0, "", 1, ref_id="1"),
        HidingRule("other", 0, "", 1, ref_id="99"),
        HidingRule("unbound", 0, "", 1),
    ]


# ---- step 1: plumbing ----
@pytest.mark.parametrize("cls", [PostgresCpqRdb, OracleCpqRdb])
def test_fetch_rules_default_shape_and_sql_unchanged(cls):
    rdb, cur = _rdb(cls, [(5, "7", "R", "3")])
    assert rdb.fetch_rules(1, "11") == [(5, 7, "R", 3)]
    assert "ref_id" not in cur.execute.call_args[0][0]


@pytest.mark.parametrize("cls", [PostgresCpqRdb, OracleCpqRdb])
def test_fetch_rules_with_ref_id(cls):
    rdb, cur = _rdb(cls, [(5, "7", "R", "3", "42"), (6, "8", "S", None, None)])
    assert rdb.fetch_rules(1, "11", with_ref_id=True) == [
        (5, 7, "R", 3, "42"), (6, 8, "S", -1, "")]
    assert "ref_id" in cur.execute.call_args[0][0]


@pytest.mark.parametrize("cls", [PostgresCpqRdb, OracleCpqRdb])
def test_fetch_value_rules_default_and_with_ref_id(cls):
    rdb, cur = _rdb(cls, [(5, "7", "R", "4", "3")])
    assert rdb.fetch_value_rules(1) == [(5, 7, "R", "4", 3)]
    assert "ref_id" not in cur.execute.call_args[0][0]
    rdb, cur = _rdb(cls, [(5, "7", "R", "4", "3", "42")])
    assert rdb.fetch_value_rules(1, with_ref_id=True) == [(5, 7, "R", "4", 3, "42")]
    assert "ref_id" in cur.execute.call_args[0][0]


def test_rule_dataclasses_ref_id_defaults_empty():
    assert HidingRule("a", 0, "", 1).ref_id == ""
    assert RecommendationRule("a", 0, "", 1).ref_id == ""
    assert ConstraintRule("a", 0, "", 1, []).ref_id == ""
    assert ValidationRule("a", 1, "m").ref_id == ""


def test_tag_ref_ids_per_row_ranges():
    rules = [HidingRule("a", 0, "", 1), HidingRule("b", 0, "", 1), HidingRule("c", 0, "", 1)]
    rule_scope.tag_ref_ids(rules, [(0, "5"), (1, ""), (1, "7")])
    assert [r.ref_id for r in rules] == ["5", "7", "7"]


# ---- step 2: filter ----
def test_flag_off_is_noop():
    _bind({"10", "1"})
    rules = _rules()
    with patch("aryx.cpq.rule_scope.get_settings", _cfg(False)):
        assert rule_scope.scope_rules_by_ancestry(rules, "t") is rules


def test_flag_on_filters_and_keeps_empty_ref_id():
    _bind({"10", "1"})
    with patch("aryx.cpq.rule_scope.get_settings", _cfg(True)):
        kept = rule_scope.scope_rules_by_ancestry(_rules(), "t")
    assert [r.rule_name for r in kept] == ["in", "anc", "unbound"]


def test_no_resolved_model_is_noop():
    rules = _rules()
    with patch("aryx.cpq.rule_scope.get_settings", _cfg(True)):
        assert rule_scope.scope_rules_by_ancestry(rules, "t") is rules  # no turn
        _bind(set(), resolved=False)
        assert rule_scope.scope_rules_by_ancestry(rules, "t") is rules


def test_value_rules_tuple_scopes_all_four_lists():
    _bind({"10"})
    tup = ([RecommendationRule("r", 0, "", 1, ref_id="99")],
           [ConstraintRule("c", 0, "", 1, [], ref_id="10")],
           [ValidationRule("v", 1, "m", ref_id="99")],
           [HidingRule("h", 0, "", 1)])
    with patch("aryx.cpq.rule_scope.get_settings", _cfg(True)):
        rec, con, val, hid = rule_scope.scope_value_rules_tuple(tup)
    assert (len(rec), len(con), len(val), len(hid)) == (0, 1, 0, 1)
