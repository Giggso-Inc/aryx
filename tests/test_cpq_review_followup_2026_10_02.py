"""Follow-up to the PR 415 review: generic-candidate exclusion at the third
call site, strict inference through the real caller, catalog invalidate-all,
rule-scope mismatch + sentinel in one call, and `~` edge cases."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq import inferred_legal_pick as ilp
from aryx.cpq import model_resolution_catalog as mrc
from aryx.cpq import rule_scope
from aryx.cpq.bml import bml_branches
from aryx.cpq.data_table import data_table_inference as inf
from aryx.cpq.data_table_bridge import conflicts as conf
from aryx.cpq.state import HidingRule, MenuOption

from tests.test_cpq_review_fixes_model_scope_2026_10_02 import _bind, _cfg, _clean, _rules  # noqa: F401


def _settings(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


# ---- #12: find_confirmed_data_table_conflicts honours the generic exclusion ----
def _run_confirmed(flag):
    seen = []

    def fake_pairs(cpq_model, *a, **k):
        seen.append(cpq_model)
        return []

    with patch.object(conf, "resolve_base_model_vn", return_value="bm"), \
            patch.object(conf, "_cpq_model_candidates", return_value=("REAL", "APXNEXT", "APXNEXT_BOM")), \
            patch.object(conf, "dt_find_inconsistent_filled_pairs_detailed", side_effect=fake_pairs), \
            patch.object(conf, "get_settings", _settings(cpq_generic_candidate_exclusion_enabled=flag)):
        conf.find_confirmed_data_table_conflicts({"bm": "B1"}, {}, 1)
    return seen


def test_confirmed_conflicts_skip_generic_pair_when_flag_on():
    assert _run_confirmed(True) == ["REAL"]


def test_confirmed_conflicts_unchanged_when_flag_off():
    assert _run_confirmed(False) == ["REAL", "APXNEXT", "APXNEXT_BOM"]


# ---- strict inference through the real caller (no allow_wider_tiers) ----
_ROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "x", "attr2": "keypad", "val2": "FULL"},
    {"CPQModel": "M1", "BaseModel": "B2", "attr1": "a", "val1": "y", "attr2": "keypad", "val2": "LIMITED"},
]


def _first(base_model):
    opts = [MenuOption(item_value="FULL", display_name="FULL", order=1),
            MenuOption(item_value="LIMITED", display_name="LIMITED", order=2)]
    with patch.object(ilp, "get_settings", _settings(cpq_infer_legal_values_enabled=True)), \
            patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value="bm"), \
            patch.object(ilp, "resolved_model_first_candidates", return_value=("M1",)), \
            patch.object(inf, "_load_all_tables", return_value=(_ROWS, [], [], [], [])), \
            patch.object(inf, "_load_basemodel_to_config_rows", return_value=[]):
        return ilp.inferred_first_available("keypad", opts, {"bm": base_model}, 1, "", {})


def test_real_caller_infers_for_base_model_with_rows():
    got = _first("B1")
    assert got is not None and got.item_value == "FULL"


def test_real_caller_falls_back_to_model_tier_for_sparse_base_model():
    # B3 has no rows at all (sparse data): the model tier is used
    got = _first("B3")
    assert got is not None and got.item_value == "FULL"


def test_real_caller_infers_nothing_when_base_model_rows_conflict_with_filled():
    # B1 HAS rows for keypad, but the filled condition contradicts them: a real
    # conflict, so no pooling from sibling base models
    opts = [MenuOption(item_value="FULL", display_name="FULL", order=1)]
    rows = [{"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "x",
             "attr2": "keypad", "val2": "FULL", "attr3": "band", "val3": "UHF"},
            {"CPQModel": "M1", "BaseModel": "B2", "attr1": "a", "val1": "y",
             "attr2": "keypad", "val2": "LIMITED", "attr3": "band", "val3": "VHF"}]
    with patch.object(ilp, "get_settings", _settings(cpq_infer_legal_values_enabled=True)),             patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value="bm"),             patch.object(ilp, "resolved_model_first_candidates", return_value=("M1",)),             patch.object(inf, "_load_all_tables", return_value=(rows, [], [], [], [])),             patch.object(inf, "_load_basemodel_to_config_rows", return_value=[]):
        got = ilp.inferred_first_available("keypad", opts, {"bm": "B1", "band": "VHF"}, 1, "", {})
    assert got is None


# ---- catalog invalidate-all ----
def test_invalidate_all_drops_every_workspace():
    from tests.test_cpq_review_fixes_model_scope_2026_10_02 import _rdb
    mrc.load_catalog(1, "X", _rdb())
    mrc.load_catalog(2, "X", _rdb())
    mrc.invalidate()
    assert mrc.cached(1, "X") is None and mrc.cached(2, "X") is None


def test_invalidate_one_workspace_keeps_others():
    from tests.test_cpq_review_fixes_model_scope_2026_10_02 import _rdb
    mrc.load_catalog(1, "X", _rdb())
    mrc.load_catalog(2, "X", _rdb())
    mrc.invalidate(1)
    assert mrc.cached(1, "X") is None and mrc.cached(2, "X") is not None


# ---- rule scope: mismatch + sentinel/unknown node in one call ----
def test_mismatch_returns_unfiltered_even_with_sentinel_and_unknown_refs():
    _bind(scope=("2",), ws=1, prefix="X")
    rules = _rules("-1", "unknown-guid", "3")
    with patch.object(rule_scope, "get_settings", _cfg(cpq_rule_scope_filter_enabled=True)):
        assert rule_scope.scope_rules_by_ancestry(rules, "x", 9, "X") is rules
        kept = rule_scope.scope_rules_by_ancestry(rules, "x", 1, "X")
    assert [r.ref_id for r in kept] == ["-1", "unknown-guid"]


# ---- `~` edge cases ----
def test_tilde_edge_cases():
    split = bml_branches._split_pipe_caret_values
    with patch.object(bml_branches, "get_settings", _settings(cpq_bml_tilde_split_enabled=True)):
        assert split(["~~"]) == []            # separators only: no values, documented no-op
        assert split(["~A"]) == ["A"]
        assert split(["A~"]) == ["A"]
        assert split(["A~~B"]) == ["A", "B"]
        assert split([""]) == []
        assert split([]) == []
