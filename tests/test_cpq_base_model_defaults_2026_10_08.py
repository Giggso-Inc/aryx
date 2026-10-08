"""Once the base model is known, an attribute the customer did not answer takes the base model's Defaultinattr default.

ws 281, "i want to quote APX N30 for US": the first pass picked the first or only option of rule-governed attributes before the
base model existed (antenna STANDARD, keypad NO KEYPAD, data cable YES, ...), tagged 'rule', and later passes kept them, so the
base model's own defaults (WHIP, LIMITED KEYPAD, NO, ...) were never reached. With the flag on a pick like that is replaced; a
value from the customer or their wording, a satisfied recommendation rule, a hidden attribute, a multi-select and the decision
anchors are left alone. Off: nothing changes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq import base_model_defaults as bmd
from aryx.cpq.auto_fill_stages import tier0_base_model_default as stage
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.state import ConfigAttr, MenuOption

BASE, ANT, KEYPAD, CABLE = "modelSelectionbaseModel_astro", "antennasType_astro", "modelSelectionKeypadType_astro", "cableDataCable_astro"
CODE = "H15UCF9PW6AN"


@pytest.fixture
def flag():
    s = get_settings()
    previous = s.cpq_base_model_defaults_enabled
    s.cpq_base_model_defaults_enabled = True
    yield s
    s.cpq_base_model_defaults_enabled = previous


def _row(base, **pairs):
    row = {"BaseModel": base}
    for i, (attr, val) in enumerate(pairs.items(), start=1):
        row[f"attr{i}"], row[f"val{i}"] = attr, val
    return row


ROWS = [
    _row(CODE, **{ANT: "WHIP"}), _row(CODE, **{KEYPAD: "LIMITED KEYPAD"}), _row(CODE, **{CABLE: "NO"}),
    _row("ALL", **{"generic_astro": "G"}), _row(CODE, **{"two_astro": "A"}), _row(CODE, **{"two_astro": "B"}),
    _row("H92UCH9PW7AN", **{ANT: "STUBBY"}),
]


def _attr(vn, values, multi=False, hidden=False, eid=None):
    return ConfigAttr(
        entity_id=eid or abs(hash(vn)) % 1_000_000, variable_name=vn, display_label=vn, required=False, default_value="",
        select_type="multi" if multi else "single", hidden=hidden,
        options=[MenuOption(item_value=v, display_name=v.title(), order=i) for i, v in enumerate(values, start=1)])


# --- the per-base-model map --------------------------------------------------------------------------------------------
def test_the_map_holds_each_attributes_single_default_for_that_base_model():
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS):
        out = bmd.base_model_defaults(CODE, 1, "p", {})
    assert out[ANT] == "WHIP" and out[KEYPAD] == "LIMITED KEYPAD" and out[CABLE] == "NO"
    assert out["generic_astro"] == "G"                      # an ALL row applies when the base model has none of its own
    assert "two_astro" not in out                           # two distinct defaults: ambiguous, never guessed


def test_an_exact_row_beats_an_all_row():
    rows = ROWS + [_row("ALL", **{ANT: "NO ANTENNA"})]
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=rows):
        assert bmd.base_model_defaults(CODE, 1, "p", {})[ANT] == "WHIP"


def test_the_map_is_built_once_per_base_model_and_cached():
    cache: dict = {}
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS) as load:
        first = bmd.base_model_defaults(CODE, 1, "p", cache)
        assert bmd.base_model_defaults(CODE, 1, "p", cache) is first
    assert load.call_count == 1
    assert bmd.base_model_defaults("", 1, "p", {}) == {}


# --- the stage ----------------------------------------------------------------------------------------------------------
def _run(attr, filled, sources, flag_on=True, rec=None, constrained=None, base_source="derived_from_known_attrs"):
    ctx = SimpleNamespace(filled={BASE: CODE, **filled}, sources={BASE: base_source, **sources}, display_filled={},
                          filled_multi={}, dt_cache={})
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p", constrained_opts=constrained, rec_by_target={1: ["r"]} if rec else {},
                            satisfied_recommendation=lambda a, o: rec)
    state = AttrResolution(vn=attr.variable_name, vn_flat=attr.variable_name.lower())
    get_settings().cpq_base_model_defaults_enabled = flag_on
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS), \
            patch.object(stage, "resolve_base_model_vn", return_value=BASE), \
            patch.object(stage.fill_log, "log_pruned"), patch.object(stage.fill_log, "log_decision"):
        stage.stage_base_model_default(SimpleNamespace(), attr, ctx, scope, state)
    return state, ctx


def test_an_earlier_pick_made_before_the_base_model_is_replaced_by_the_default(flag):
    attr = _attr(ANT, ["STANDARD", "WHIP", "STUBBY"])
    state, ctx = _run(attr, {ANT: "STANDARD"}, {ANT: "rule"})
    assert state.value == "WHIP" and state.source == "defaultinattr" and ANT not in ctx.filled


def test_an_attribute_still_empty_gets_the_default(flag):
    state, _ = _run(_attr(KEYPAD, ["NO KEYPAD", "LIMITED KEYPAD"]), {}, {})
    assert state.value == "LIMITED KEYPAD"


def test_a_blind_guess_is_replaced_too(flag):
    state, _ = _run(_attr(CABLE, ["YES", "NO"]), {CABLE: "YES"}, {CABLE: "blind_pick_rule_governed"})
    assert state.value == "NO"


def test_a_value_from_the_customer_or_their_wording_stays(flag):
    for source in ("user", "hint", "auto", "data_table", "defaultinattr"):
        state, _ = _run(_attr(ANT, ["STANDARD", "WHIP"]), {ANT: "STANDARD"}, {ANT: source})
        assert state.value is None, source


def test_a_value_that_is_already_the_default_is_left_alone(flag):
    state, _ = _run(_attr(ANT, ["STANDARD", "WHIP"]), {ANT: "whip"}, {ANT: "rule"})
    assert state.value is None


def test_a_recommendation_rule_that_applies_now_wins_over_the_table(flag):
    state, _ = _run(_attr(ANT, ["STANDARD", "WHIP"]), {ANT: "STANDARD"}, {ANT: "rule"}, rec=("STANDARD", "Standard", "some rule"))
    assert state.value is None


def test_a_default_that_is_not_an_option_or_is_constrained_out_is_not_used(flag):
    attr = _attr(ANT, ["STANDARD", "STUBBY"])                      # WHIP is not an option
    assert _run(attr, {ANT: "STANDARD"}, {ANT: "rule"})[0].value is None
    attr = _attr(ANT, ["STANDARD", "WHIP"], eid=7)
    assert _run(attr, {ANT: "STANDARD"}, {ANT: "rule"}, constrained={7: ["STANDARD"]})[0].value is None
    assert _run(attr, {ANT: "STANDARD"}, {ANT: "rule"}, constrained={7: ["STANDARD", "WHIP"]})[0].value == "WHIP"


def test_hidden_multi_select_and_anchor_attributes_are_not_touched(flag):
    assert _run(_attr(ANT, ["WHIP"], hidden=True), {}, {})[0].value is None
    assert _run(_attr(ANT, ["WHIP"], multi=True), {}, {})[0].value is None
    assert _run(_attr(BASE, ["WHIP"]), {}, {})[0].value is None


def test_nothing_happens_without_a_real_base_model(flag):
    attr = _attr(ANT, ["STANDARD", "WHIP"])
    ctx = SimpleNamespace(filled={ANT: "STANDARD"}, sources={ANT: "rule"}, display_filled={}, filled_multi={}, dt_cache={})
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p", constrained_opts=None, rec_by_target={},
                            satisfied_recommendation=None)
    state = AttrResolution(vn=ANT, vn_flat=ANT.lower())
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS), patch.object(stage, "resolve_base_model_vn", return_value=BASE):
        stage.stage_base_model_default(SimpleNamespace(), attr, ctx, scope, state)       # no base model in filled
        assert state.value is None
        ctx.filled[BASE], ctx.sources[BASE] = CODE, "blind_pick_rule_governed"            # a guessed base model is not one
        stage.stage_base_model_default(SimpleNamespace(), attr, ctx, scope, state)
        assert state.value is None


def test_with_the_flag_off_nothing_changes(flag):
    state, ctx = _run(_attr(ANT, ["STANDARD", "WHIP"]), {ANT: "STANDARD"}, {ANT: "rule"}, flag_on=False)
    assert state.value is None and ctx.filled[ANT] == "STANDARD"


def test_the_stage_runs_right_after_the_guard_and_before_the_already_filled_stage():
    from aryx.cpq.auto_fill_stages import coordinator

    names = [f.__module__.rsplit(".", 1)[-1] for f in coordinator._STAGES]
    assert names.index("tier0_base_model_default") == names.index("tier0_not_applicable_guard") + 1
    assert names.index("tier0_base_model_default") < names.index("tier0_already_filled")
