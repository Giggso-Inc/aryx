"""Flag-gated ports of aryxent Data Table fixes into dev_oci (D7, D8, D10,
D11, D13/D17). Every flag is off by default and must leave behaviour
unchanged when off.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.cpq import model_resolution as mr
from aryx.cpq.constraint_rules import constraint_rules_dt_narrowing as dtn
from aryx.cpq.data_table import data_table_defaultinattr as dd
from aryx.cpq.data_table import data_table_derive_base_model as dbm
from aryx.cpq.data_table import data_table_inference as inf
from aryx.cpq.data_table.data_table_shapes import _detect_shape, _is_defaultinattr_shaped
from aryx.cpq.data_table_bridge import conflicts as conf
from aryx.cpq.grid_quantity import narrow as gq_narrow
from aryx.cpq.grid_quantity import pending as gq_pending
from aryx.cpq.state import ConfigAttr, MenuOption


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


def _bind(cpq_model="APX4000XH", display=("APX 4000",)):
    cand = mr.ModelCandidate(
        cpq_model=cpq_model, display_names=frozenset(display), node_name=None,
        node_id=None, base_models=frozenset(), match="exact", is_upgrade=False,
        soft_deleted=False,
    )
    res = mr.ModelResolution(
        chosen=cand, alternatives=(), deciding_step="x", source="hint",
        scope_node_ids=frozenset(),
    )
    mr.bind_turn(mr.TurnModelContext(res, 1, ""))


# ---- D7: Defaultinattr ----
def test_defaultinattr_shape_detection():
    keys = {"BaseModel", "attr1", "val1", "attr2", "val2"}
    assert _is_defaultinattr_shaped(keys)
    assert not _is_defaultinattr_shaped(keys | {"CPQModel"})
    assert _detect_shape(keys) is None  # not pooled into the 5 buckets


ROWS = [
    {"BaseModel": "BM1", "attr1": "color", "val1": "RED"},
    {"BaseModel": "ALL", "attr1": "color", "val1": "BLUE", "attr2": "size", "val2": "L"},
]


def test_defaultinattr_resolver_exact_beats_all_and_ambiguity():
    with patch.object(dd, "_load_defaultinattr_rows", return_value=ROWS):
        assert dd.resolve_defaultinattr_value("BM1", "color", 1) == "RED"
        assert dd.resolve_defaultinattr_value("BM2", "color", 1) == "BLUE"
        assert dd.resolve_defaultinattr_value("BM2", "size", 1) == "L"
        assert dd.resolve_defaultinattr_value("BM2", "none", 1) is None
    dup = ROWS + [{"BaseModel": "BM1", "attr1": "color", "val1": "GREEN"}]
    with patch.object(dd, "_load_defaultinattr_rows", return_value=dup):
        assert dd.resolve_defaultinattr_value("BM1", "color", 1) is None


def test_defaultinattr_wiring_flag_off_and_on():
    opts = [_opt("RED"), _opt("BLUE")]
    with patch.object(dd, "_load_defaultinattr_rows", return_value=ROWS):
        with patch.object(conf, "get_settings", _cfg(cpq_defaultinattr_shape_enabled=False)):
            assert conf._defaultinattr_option("color", "BM1", opts, 1, "", None) is None
        with patch.object(conf, "get_settings", _cfg(cpq_defaultinattr_shape_enabled=True)):
            got = conf._defaultinattr_option("color", "BM1", opts, 1, "", None)
            assert got is not None and got.item_value == "RED"
            # default that is not a real option -> None
            assert conf._defaultinattr_option("color", "BM1", [_opt("X")], 1, "", None) is None


# ---- D8: inferred legal values ----
CROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "attr1": "a", "val1": "x", "attr2": "keypad", "val2": "FULL"},
    {"CPQModel": "M1", "BaseModel": "B2", "attr1": "a", "val1": "y", "attr2": "keypad", "val2": "LIMITED"},
    {"CPQModel": "SIB", "BaseModel": "B9", "attr1": "a", "val1": "z", "attr2": "keypad", "val2": "TOUCH"},
]
FAMILY = [
    {"displayModel": "m", "cpqModel": "M1", "baseModel": "B1", "productLine": "PL"},
    {"displayModel": "s", "cpqModel": "M3", "baseModel": "B1", "productLine": "PL"},
    {"displayModel": "q", "cpqModel": "SIB", "baseModel": "B9", "productLine": "PL"},
]


def test_infer_tiers():
    tables = (CROWS, [], [], [], [])
    with patch.object(inf, "_load_all_tables", return_value=tables), \
            patch.object(inf, "_load_basemodel_to_config_rows", return_value=FAMILY):
        assert inf.infer_implied_legal_values("keypad", "m1", 1, base_model="B1") == (["FULL"], "model_basemodel")
        assert inf.infer_implied_legal_values("keypad", "M1", 1) == (["FULL", "LIMITED"], "model")
        # M3 has no rows -> family tier pools M1 + SIB siblings
        assert inf.infer_implied_legal_values("keypad", "M3", 1) == (["FULL", "LIMITED", "TOUCH"], "family")
        assert inf.infer_implied_legal_values("nope", "M1", 1) is None
        assert inf.infer_implied_legal_values("keypad", "", 1) is None


def test_inferred_first_available_flag_off_and_on():
    from aryx.cpq import inferred_legal_pick as ilp

    opts = [_opt("NONE", 1), _opt("LIMITED", 3), _opt("FULL", 2)]
    kw = dict(valid_opts=opts, filled={}, workspace_id=1, catalog_prefix="", cache=None)
    with patch.object(ilp, "get_settings", _cfg(cpq_infer_legal_values_enabled=False)):
        assert ilp.inferred_first_available("keypad", **kw) is None
    with patch.object(ilp, "get_settings", _cfg(cpq_infer_legal_values_enabled=True)), \
            patch("aryx.cpq.catalog_profile.resolve_base_model_vn", return_value="bm"), \
            patch.object(ilp, "resolved_model_first_candidates", return_value=["M1"]), \
            patch.object(ilp, "infer_implied_legal_values", return_value=(["FULL", "LIMITED"], "model")):
        got = ilp.inferred_first_available("keypad", **kw)
        assert got is not None and got.item_value == "FULL"  # lowest order among legal


# ---- D10: derive base model ----
BROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "attr1": "band", "val1": "UHF", "attr2": "keypad", "val2": "FULL"},
    {"CPQModel": "M1", "BaseModel": "B2", "attr1": "band", "val1": "UHF", "attr2": "keypad", "val2": "LIMITED"},
    {"CPQModel": "M1", "BaseModel": "B3", "attr1": "band", "val1": "VHF", "attr2": "keypad", "val2": "FULL"},
    {"CPQModel": "M1", "BaseModel": "ALL", "attr1": "z", "val1": "q"},
]


def test_derive_base_model_narrows_to_one_or_none():
    with patch.object(dbm, "_load_all_tables", return_value=(BROWS, [], [], [], [])):
        assert dbm.derive_base_model_from_known_attrs("M1", {"band": "uhf", "keypad": "full"}, 1) == "B1"
        assert dbm.derive_base_model_from_known_attrs("M1", {"band": "UHF"}, 1) is None  # B1/B2 remain
        assert dbm.derive_base_model_from_known_attrs("M1", {}, 1) is None
        assert dbm.derive_base_model_from_known_attrs("NOPE", {"band": "UHF"}, 1) is None


def test_derived_base_model_option_flag_off_and_on():
    from aryx.cpq import derive_base_model_pick as dbp

    opts = [_opt("B1"), _opt("B2")]
    args = (opts, {"band": "UHF"}, 1, "", None)
    with patch.object(dbp, "get_settings", _cfg(cpq_derive_base_model_enabled=False)):
        assert dbp.derived_base_model_option(*args) is None
    with patch.object(dbp, "get_settings", _cfg(cpq_derive_base_model_enabled=True)), \
            patch.object(dbp, "resolved_model_first_candidates", return_value=["M1"]), \
            patch.object(dbp, "derive_base_model_from_known_attrs", return_value="B2"):
        got = dbp.derived_base_model_option(*args)
        assert got is not None and got.item_value == "B2"
    with patch.object(dbp, "get_settings", _cfg(cpq_derive_base_model_enabled=True)), \
            patch.object(dbp, "resolved_model_first_candidates", return_value=["M1"]), \
            patch.object(dbp, "derive_base_model_from_known_attrs", return_value="B9"):
        assert dbp.derived_base_model_option(*args) is None  # not a real option


# ---- D13/D17: Whitelist narrowing ----
def test_constraint_narrowing_pass():
    a1 = _attr(1, "feat", ["A", "B", "C"])
    a2 = _attr(2, "one", ["A", "B"])
    a3 = _attr(3, "done", ["A", "B"])
    fake = {"feat": ["A", "B"], "one": ["A"], "done": ["A", "B"]}
    constrained: dict = {}
    contributions: dict = {}
    with patch.object(conf, "_resolve_narrowed_legal_values", side_effect=lambda vn, *a, **k: fake[vn]):
        dtn.apply_data_table_narrowing(
            [a1, a2, a3], {"done": "A"}, 1, "", None, constrained, contributions,
        )
        assert constrained == {1: ["A", "B"]}  # 1-value and answered attrs skipped
        dtn.apply_data_table_narrowing([a1], {}, None, "", None, {}, {})  # no workspace: no-op


def test_late_pass_kwargs_follow_flag():
    from aryx.cpq.rules_loop import rules_loop_pass_late as late

    with patch.object(late, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=False)):
        assert late._whitelist_narrow_kwargs() == {}
    with patch.object(late, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=True)):
        assert late._whitelist_narrow_kwargs() == {"narrow_from_data_tables": True}


def test_grid_narrow_helpers_follow_flag():
    with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=False)):
        assert gq_narrow.grid_narrow_kwargs(1, "p") == {}
        assert gq_narrow.whitelist_narrowed_selector_options("s", {}, 1, "", None) is None
    with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=True)):
        assert gq_narrow.grid_narrow_kwargs(1, "p") == {"workspace_id": 1, "catalog_prefix": "p"}
        assert gq_narrow.grid_narrow_kwargs(None, "p") == {}
        with patch.object(conf, "_resolve_narrowed_legal_values", return_value=["a"]):
            assert gq_narrow.whitelist_narrowed_selector_options("s", {}, 1, "", None) == ["a"]


def test_pending_grid_quantities_narrowed_by_whitelist():
    sel = _attr(10, "sel", ["a", "b"])
    qa, qb = _attr(11, "qa"), _attr(12, "qb")
    links = {"sel": {"a": "qa", "b": "qb"}}
    with patch.object(gq_pending, "resolve_array_grid_links", return_value=links):
        base = gq_pending.resolve_pending_grid_quantities([sel, qa, qb], {}, {})
        assert [a.variable_name for a in base] == ["qa", "qb"]
        with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=False)), \
                patch.object(conf, "_resolve_narrowed_legal_values", return_value=["a"]):
            off = gq_pending.resolve_pending_grid_quantities(
                [sel, qa, qb], {}, {}, workspace_id=1, catalog_prefix="")
            assert [a.variable_name for a in off] == ["qa", "qb"]
        with patch.object(gq_narrow, "get_settings", _cfg(cpq_whitelist_narrow_questions_enabled=True)), \
                patch.object(conf, "_resolve_narrowed_legal_values", return_value=["a"]):
            on = gq_pending.resolve_pending_grid_quantities(
                [sel, qa, qb], {}, {}, workspace_id=1, catalog_prefix="")
            assert [a.variable_name for a in on] == ["qa"]


# ---- D11: exact-first product match ----
def _norm(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


OPTIONS = [("APX4000XHFLASHPORT", "APX 4000XH FLASHPORT"), ("APX4000XH", "APX 4000XH")]


def test_product_option_match_flag_off_keeps_first_substring_hit():
    from aryx.cpq import product_match_exact_first as pm

    with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=False)):
        got = pm.match_option_name(OPTIONS, _norm("APX 4000XH"), 4, _norm)
        assert got == "APX 4000XH FLASHPORT"


def test_product_option_match_exact_wins_when_flag_on():
    from aryx.cpq import product_match_exact_first as pm

    with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=True)):
        assert pm.match_option_name(OPTIONS, _norm("APX 4000XH"), 4, _norm) == "APX 4000XH"
        # no exact: the closest-length containing name wins, not the first
        loose = [("APX4000XHFLASHPORT", "APX 4000XH FLASHPORT"), ("APX4000XHPLUS", "APX 4000XH PLUS")]
        assert pm.match_option_name(loose, _norm("APX 4000XH"), 4, _norm) == "APX 4000XH PLUS"
        assert pm.match_option_name(OPTIONS, _norm("zzzz"), 4, _norm) is None


def test_resolved_model_seed_texts():
    from aryx.cpq import product_match_exact_first as pm

    opts = [_opt("APX4000XHFLASHPORT"), _opt("apx4000xh")]
    try:
        _bind("APX4000XH")
        with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=False)):
            assert pm.resolved_model_seed_texts(opts) == []
        with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=True)):
            assert pm.resolved_model_seed_texts(opts) == ["apx4000xh"]
            assert pm.resolved_model_seed_texts([_opt("OTHER")]) == []
        mr.bind_turn(None)
        with patch.object(pm, "get_settings", _cfg(cpq_product_match_exact_first_enabled=True)):
            assert pm.resolved_model_seed_texts(opts) == []
    finally:
        mr.bind_turn(None)


def test_new_flags_default_off():
    from aryx.config.config_cpq_intent import CpqIntentSettingsMixin

    fields = CpqIntentSettingsMixin.model_fields
    for name in (
        "cpq_defaultinattr_shape_enabled", "cpq_infer_legal_values_enabled",
        "cpq_derive_base_model_enabled", "cpq_whitelist_narrow_questions_enabled",
        "cpq_product_match_exact_first_enabled",
    ):
        assert fields[name].default is False
        assert fields[name].description
