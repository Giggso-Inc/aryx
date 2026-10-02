"""PR 412 review fixes for the flag-gated Data Table ports (High 3/4,
Medium 6/7/8/11/12, Low `~` escape). Every behaviour change here is behind
the same flags as the original port; flag-off behaviour is unchanged.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq import product_match_exact_first as pm
from aryx.cpq.bml import bml_branches
from aryx.cpq.constraint_rules import constraint_rules_dt_narrowing as dtn  # noqa: F401
from aryx.cpq.data_table import data_table_derive_base_model as dbm
from aryx.cpq.data_table import data_table_inference as inf
from aryx.cpq.data_table import data_table_loader as loader
from aryx.cpq.data_table_bridge import conflicts as conf
from aryx.cpq.engine import CpqEngine
from aryx.cpq.grid_quantity import narrow as gq_narrow
from aryx.cpq.grid_quantity import pending as gq_pending
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


def _opt(v, order=999):
    return MenuOption(item_value=v, display_name=v, order=order)


def _attr(eid, vn, opts=()):
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=vn, required=False,
        default_value="", options=[_opt(o) for o in opts],
    )


def _norm(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


@pytest.fixture(autouse=True)
def _clear_caches():
    loader._clear_tables_cache()
    yield
    loader._clear_tables_cache()


class _FakeRdb:
    def __init__(self, grouped):
        self.grouped = grouped
        self.calls = 0

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        self.calls += 1
        return self.grouped


# ---- High 3: exact-first matching, option inside the question ----
def test_option_inside_question_picks_most_specific_option():
    options = [("APX4000XH", "APX 4000XH"), ("APX4000XHFLASHPORT", "APX 4000XH FLASHPORT")]
    hint = _norm("quote for 10 APX 4000XH Flashport radios")
    with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=True)):
        assert pm.match_option_name(options, hint, 4, _norm) == "APX 4000XH FLASHPORT"
    # flag off: original first-hit behaviour is untouched
    with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=False)):
        assert pm.match_option_name(options, hint, 4, _norm) == "APX 4000XH"


def test_display_name_exact_check_not_skipped_after_item_value_substring_hit():
    options = [
        ("APX4000XHEXTRA", "APX 4000XH"),  # item_value is a loose hit, display_name is exact
        ("APX4000XHEXT", "APX4000XHEXT"),  # closer in length, loose only
    ]
    with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=True)):
        assert pm.match_option_name(options, _norm("APX 4000XH"), 4, _norm) == "APX 4000XH"


# ---- High 4: module-level TTL caches for the standalone scans ----
def test_defaultinattr_loader_second_call_does_not_rescan():
    rdb = _FakeRdb({"Defaultinattr": [(1, {"BaseModel": "BM1", "attr1": "c", "val1": "RED"})]})
    with patch.object(loader, "get_cpq_rdb", return_value=rdb):
        first = loader._load_defaultinattr_rows(1, "", {})  # separate per-call caches
        second = loader._load_defaultinattr_rows(1, "", {})
        third = loader._load_defaultinattr_rows(1, "", None)
    assert rdb.calls == 1
    assert first == second == third and len(first) == 1
    loader._clear_tables_cache()
    with patch.object(loader, "get_cpq_rdb", return_value=rdb):
        loader._load_defaultinattr_rows(1, "", None)
    assert rdb.calls == 2  # clear hook really clears


def test_basemodel_to_config_loader_second_call_does_not_rescan():
    row = {"displayModel": "m", "cpqModel": "M1", "baseModel": "B1", "productLine": "PL"}
    rdb = _FakeRdb({"Basemodeltoconfig": [(1, row)], "Other": [(2, {"x": "y"})]})
    with patch.object(loader, "get_cpq_rdb", return_value=rdb):
        a = inf._load_basemodel_to_config_rows(1, "", {})
        b = inf._load_basemodel_to_config_rows(1, "", {})
    assert rdb.calls == 1
    assert a == b == [row]


# ---- Medium 6: Defaultinattr fallback only when the Whitelist has no coverage ----
_DEFAULT_ROW = {"BaseModel": "BM1", "attr1": "color", "val1": "RED"}


def _wl(base_model, value, *conds):
    row = {"CPQModel": "M1", "BaseModel": base_model, "attr1": "color", "val1": value}
    for i, (a, v) in enumerate(conds, start=2):
        row[f"attr{i}"] = a
        row[f"val{i}"] = v
    return (1, row)


def _resolve(grouped, valid=("RED", "BLUE")):
    rdb = _FakeRdb(grouped)
    with patch.object(loader, "get_cpq_rdb", return_value=rdb), \
            patch.object(conf, "resolve_base_model_vn", return_value="bm"), \
            patch.object(conf, "_cpq_model_candidates", return_value=("M1",)), \
            patch.object(conf, "get_settings", _cfg(
                cpq_defaultinattr_shape_enabled=True, cpq_generic_candidate_exclusion_enabled=False)):
        return conf._resolve_via_data_tables(
            "color", {"bm": "BM1", "size": "L"}, [_opt(v) for v in valid], 1, "", {},
        )


def test_defaultinattr_fallback_when_whitelist_has_no_rows():
    got = _resolve({"Defaultinattr": [(9, _DEFAULT_ROW)]})
    assert got is not None and got.item_value == "RED"


def test_defaultinattr_does_not_override_whitelist_empty_legal_set():
    # Whitelist rows exist for color/BM1 but their condition (size=S) does not
    # match filled size=L -> real "no legal value" answer; default RED must not win.
    grouped = {"Whitelist": [_wl("BM1", "BLUE", ("size", "S"))], "Defaultinattr": [(9, _DEFAULT_ROW)]}
    assert _resolve(grouped) is None


def test_defaultinattr_does_not_override_whitelist_ambiguous_set():
    grouped = {"Whitelist": [_wl("BM1", "RED"), _wl("BM1", "BLUE")], "Defaultinattr": [(9, _DEFAULT_ROW)]}
    assert _resolve(grouped) is None


def test_whitelist_single_value_still_wins_over_default():
    grouped = {"Whitelist": [_wl("BM1", "BLUE")], "Defaultinattr": [(9, _DEFAULT_ROW)]}
    got = _resolve(grouped)
    assert got is not None and got.item_value == "BLUE"


# ---- Medium 7: narrowing must not empty a rule-derived intersection ----
def _narrowing_scenario(narrowed):
    cond = _attr(10, "cond", ["X"])
    target = _attr(11, "target", ["A", "B", "C"])
    rule = ConstraintRule(
        rule_name="restrict target", condition_attr_id=10, condition_value="X",
        target_attr_id=11, allowed_values=["A", "B"], conditions=[(10, "X", "4")],
    )
    with patch.object(
        conf, "_resolve_narrowed_legal_values",
        side_effect=lambda vn, *a, **k: narrowed if vn == "target" else None,
    ):
        return CpqEngine().apply_constraint_rules(
            [cond, target], [rule], filled={"cond": "X"}, workspace_id=1,
            narrow_from_data_tables=True,
        )


def test_narrowing_intersects_with_real_constraint_rule():
    assert _narrowing_scenario(["B", "C"]) == {11: ["B"]}


def test_narrowing_that_would_empty_intersection_is_skipped():
    result = _narrowing_scenario(["C", "D"])
    assert result == {11: ["A", "B"]}  # rule's set kept, not emptied


def test_narrowing_alone_still_applies_without_a_rule():
    target = _attr(11, "target", ["A", "B", "C"])
    with patch.object(conf, "_resolve_narrowed_legal_values", return_value=["B", "C"]):
        result = CpqEngine().apply_constraint_rules(
            [target], [], filled={}, workspace_id=1, narrow_from_data_tables=True,
        )
    assert result == {11: ["B", "C"]}


# ---- Medium 8: grid pending narrowing is case-insensitive and shares a cache ----
def test_grid_pending_case_mismatch_and_shared_cache():
    sel = _attr(10, "sel", ["700/800 MHZ"])
    sel2 = _attr(13, "sel2", ["UHF"])
    qa, qb = _attr(11, "qa"), _attr(12, "qb")
    links = {"sel": {"700/800 mhz": "qa"}, "sel2": {"uhf": "qb"}}
    seen = []

    def fake_narrowed(vn, filled, ws, prefix, cache):
        seen.append(cache)
        return ["700/800 MHz"] if vn == "sel" else ["uhf"]

    with patch.object(gq_pending, "resolve_array_grid_links", return_value=links), \
            patch.object(gq_pending, "whitelist_narrowed_selector_options", side_effect=fake_narrowed):
        got = gq_pending.resolve_pending_grid_quantities(
            [sel, sel2, qa, qb], {}, {}, workspace_id=1, catalog_prefix="",
        )
    assert [a.variable_name for a in got] == ["qa", "qb"]
    assert seen[0] is not None and all(c is seen[0] for c in seen)  # one cache for the call


def test_grid_narrow_kwargs_passes_cache_only_when_flag_on():
    cache: dict = {}
    with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=True)):
        assert gq_narrow.grid_narrow_kwargs(1, "p", cache)["dt_cache"] is cache
        assert "dt_cache" not in gq_narrow.grid_narrow_kwargs(1, "p")
    with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=False)):
        assert gq_narrow.grid_narrow_kwargs(1, "p", cache) == {}


# ---- Medium 11: derive base model ----
_DROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "attr1": "keypad", "val1": "FULL", "attr2": "feat", "val2": "X"},
    {"CPQModel": "M1", "BaseModel": "B2", "attr1": "keypad", "val1": "LIMITED"},
    {"CPQModel": "M1", "BaseModel": "B3", "attr1": "band", "val1": "VHF", "attr2": "feat", "val2": "Y"},
]


def test_derive_does_not_exclude_base_model_without_rows_for_attr():
    with patch.object(dbm, "_load_all_tables", return_value=(_DROWS, [], [], [], [])):
        # B2 has keypad rows (not FULL) -> excluded; B3 has none -> unrestricted, kept
        assert dbm.derive_base_model_from_known_attrs("M1", {"keypad": "FULL"}, 1) is None
        # a second attr that does restrict B3 settles it
        assert dbm.derive_base_model_from_known_attrs(
            "M1", {"keypad": "FULL", "feat": "X"}, 1) == "B1"


def test_derive_ignores_blind_filled_attrs():
    with patch.object(dbm, "_load_all_tables", return_value=(_DROWS, [], [], [], [])):
        known = {"keypad": "FULL", "feat": "X"}
        assert dbm.derive_base_model_from_known_attrs("M1", known, 1) == "B1"
        assert dbm.derive_base_model_from_known_attrs(
            "M1", known, 1, ignore_attrs={"feat"}) is None


def test_derived_option_passes_blind_sources_as_ignored():
    from aryx.cpq import derive_base_model_pick as dbp

    captured = {}

    def fake_derive(cpq_model, filled, ws, prefix, cache, ignore_attrs=frozenset()):
        captured["ignore"] = set(ignore_attrs)
        return "B1"

    with patch.object(dbp, "get_settings", _cfg(cpq_derive_base_model_enabled=True)), \
            patch.object(dbp, "resolved_model_first_candidates", return_value=["M1"]), \
            patch.object(dbp, "derive_base_model_from_known_attrs", side_effect=fake_derive):
        got = dbp.derived_base_model_option(
            [_opt("B1")], {"a": "1", "b": "2", "c": "3"}, 1, "", None,
            sources={"a": "user", "b": "blind_pick_governed", "c": "default_first_available"},
        )
    assert got is not None and captured["ignore"] == {"b", "c"}


# ---- Medium 12: inference restricted to the base-model tier ----
_IROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "x", "attr2": "keypad", "val2": "FULL"},
    {"CPQModel": "M1", "BaseModel": "B2", "attr1": "a", "val1": "y", "attr2": "keypad", "val2": "LIMITED"},
]


def test_inference_scoped_to_base_model_tier_unless_allowed():
    tables = (_IROWS, [], [], [], [])
    with patch.object(inf, "_load_all_tables", return_value=tables), \
            patch.object(inf, "_load_basemodel_to_config_rows", return_value=[]):
        assert inf.infer_implied_legal_values("keypad", "M1", 1, base_model="B1") == (["FULL"], "model_basemodel")
        # B3 has no rows at all (sparse data): falls back to the model tier
        assert inf.infer_implied_legal_values("keypad", "M1", 1, base_model="B3") == (["FULL", "LIMITED"], "model")
        assert inf.infer_implied_legal_values(
            "keypad", "M1", 1, base_model="B3", allow_wider_tiers=True,
        ) == (["FULL", "LIMITED"], "model")
        # no base model known: nothing to restrict by
        assert inf.infer_implied_legal_values("keypad", "M1", 1) == (["FULL", "LIMITED"], "model")


def test_inference_honours_other_conditions_of_the_rows():
    rows = [
        {"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "x",
         "attr2": "keypad", "val2": "FULL", "attr3": "band", "val3": "UHF"},
        {"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "y",
         "attr2": "keypad", "val2": "LIMITED", "attr3": "band", "val3": "VHF"},
    ]
    with patch.object(inf, "_load_all_tables", return_value=(rows, [], [], [], [])):
        both = inf.infer_implied_legal_values("keypad", "M1", 1, base_model="B1")
        assert both == (["FULL", "LIMITED"], "model_basemodel")
        only = inf.infer_implied_legal_values(
            "keypad", "M1", 1, base_model="B1", filled={"band": "uhf"})
        assert only == (["FULL"], "model_basemodel")
        none = inf.infer_implied_legal_values(
            "keypad", "M1", 1, base_model="B1", filled={"band": "UHF", "x": "y"})
        assert none == (["FULL"], "model_basemodel")


# ---- Low: `~` escape ----
def test_tilde_split_honours_backslash_escape():
    split = bml_branches._split_pipe_caret_values
    with patch.object(bml_branches, "get_settings", _cfg(cpq_bml_tilde_split_enabled=True)):
        assert split(["A~B~C"]) == ["A", "B", "C"]
        assert split([r"A\~B"]) == ["A~B"]
        assert split([r"A\~B~C"]) == ["A~B", "C"]
        assert split(["plain"]) == ["plain"]
    with patch.object(bml_branches, "get_settings", _cfg(cpq_bml_tilde_split_enabled=False)):
        assert split(["A~B"]) == ["A~B"]
        assert split([r"A\~B"]) == [r"A\~B"]  # flag off: byte-identical
