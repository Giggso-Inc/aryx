"""Once the base model is known, an attribute the customer did not answer takes the base model's Defaultinattr default.

ws 281, "i want to quote APX N30 for US": the first pass picked the first or only option of rule-governed attributes
before the base model existed (antenna STANDARD, keypad NO KEYPAD, data cable YES, ...), tagged 'rule', and later passes
kept them, so the base model's own defaults (WHIP, LIMITED KEYPAD, NO, ...) were never reached.

Precedence with the flag on: the customer's words, then a recommendation rule that applies now, then the base model's
default, then the generic default. Two stages give that order: one clears a replaceable earlier pick, a later one writes
the default only if the hint and recommendation stages left the attribute empty. Off: nothing changes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq import base_model_defaults as bmd
from aryx.cpq.auto_fill_stages import coordinator
from aryx.cpq.data_table import data_table_loader
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule

BASE, PRODUCT = "modelSelectionbaseModel_astro", "productSelectionProduct_all"
ANT, KEYPAD, CABLE = "antennasType_astro", "modelSelectionKeypadType_astro", "cableDataCable_astro"
SELECT = "modelSelectionSelectModel_astro"
CODE, CODE2 = "H15UCF9PW6AN", "H15KDF9PW6AN"


def _row(base, attr, val):
    return {"BaseModel": base, "attr1": attr, "val1": val}


ROWS = [
    _row(CODE, ANT, "WHIP"), _row(CODE, KEYPAD, "LIMITED KEYPAD"), _row(CODE, CABLE, "NO"), _row(CODE, SELECT, "S1"),
    _row(CODE2, KEYPAD, "FULL KEYPAD"), _row("ALL", "generic_astro", "G"),
    _row(CODE, "two_astro", "A"), _row(CODE, "two_astro", "B"),
]


@pytest.fixture
def flag():
    s = get_settings()
    previous = s.cpq_base_model_defaults_enabled
    s.cpq_base_model_defaults_enabled = True
    data_table_loader._clear_tables_cache()
    yield s
    s.cpq_base_model_defaults_enabled = previous
    data_table_loader._clear_tables_cache()


def _attr(vn, pairs, eid, hidden=False, multi=False):
    options = [MenuOption(item_value=v, display_name=d, order=i) for i, (v, d) in enumerate(pairs, start=1)]
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      select_type="multi" if multi else "single", hidden=hidden, options=options)


def _attrs():
    return [
        _attr(PRODUCT, [("APX N30", "APX N30")], 1),
        _attr(BASE, [(CODE, CODE), (CODE2, CODE2)], 2),
        _attr(KEYPAD, [("LIMITED KEYPAD", "Limited Keypad"), ("FULL KEYPAD", "Full Keypad"),
                       ("NO KEYPAD", "No Keypad")], 3),
        _attr(ANT, [("STANDARD", "Standard"), ("WHIP", "Whip")], 4),
        _attr(CABLE, [("YES", "Yes"), ("NO", "No")], 5),
        _attr(SELECT, [("S1", "S1"), ("S2", "S2")], 6),
    ]


class _EmptyRdb:
    """The data layer, with no tables: only the Defaultinattr rows (patched) matter here."""

    def list_ontology_types(self, workspace_id):
        return []

    def fetch_entities_by_type(self, workspace_id, type_suffix, catalog_prefix=""):
        return []

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return []

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        return {}


def _fill(filled=None, sources=None, hints=None, rec_rules=None, base=CODE, rows=ROWS):
    """The real auto_fill, with the base model given. Returns (filled, pending names, sources)."""
    source = {PRODUCT: "user", BASE: "derived_from_known_attrs", **(sources or {})}
    with patch.object(data_table_loader, "get_cpq_rdb", lambda: _EmptyRdb()), \
            patch.object(bmd, "_load_defaultinattr_rows", return_value=rows):
        out, _display, pending = CpqEngine().auto_fill(
            _attrs(), hints or {}, already_filled={PRODUCT: "APX N30", BASE: base, **(filled or {})},
            filled_source=source, rec_rules=rec_rules, workspace_id=7)
    return out, {a.variable_name for a in pending}, source


# --- the per-base-model map ------------------------------------------------------------------------------------------
def test_the_map_holds_each_attributes_single_default_for_that_base_model():
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS):
        out = bmd.base_model_defaults(CODE, 1, "p", {})
    assert out[ANT] == "WHIP" and out[KEYPAD] == "LIMITED KEYPAD" and out[CABLE] == "NO"
    assert out["generic_astro"] == "G"                      # an ALL row applies when the base model has none of its own
    assert "two_astro" not in out                           # two distinct defaults: ambiguous, never guessed


def test_an_exact_row_beats_an_all_row():
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS + [_row("ALL", ANT, "NO ANTENNA")]):
        assert bmd.base_model_defaults(CODE, 1, "p", {})[ANT] == "WHIP"


def test_the_base_model_code_compares_case_insensitively_like_all():
    """Review: a code stored in another case must not fall back to the generic ALL rows."""
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS + [_row("ALL", ANT, "NO ANTENNA")]):
        assert bmd.base_model_defaults(CODE.lower(), 1, "p", {})[ANT] == "WHIP"
        assert bmd.base_model_defaults(f" {CODE} ", 1, "p", {})[ANT] == "WHIP"


def test_the_map_is_built_once_per_base_model_and_cached():
    cache: dict = {}
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS) as load:
        first = bmd.base_model_defaults(CODE, 1, "p", cache)
        assert bmd.base_model_defaults(CODE.lower(), 1, "p", cache) is first
    assert load.call_count == 1 and bmd.base_model_defaults("", 1, "p", {}) == {}


# --- through the real auto_fill ---------------------------------------------------------------------------------
def test_an_empty_attribute_gets_the_default_and_an_earlier_rule_pick_is_replaced(flag):
    out, _pending, sources = _fill(filled={ANT: "STANDARD"}, sources={ANT: "rule"})
    assert out[ANT] == "WHIP" and sources[ANT] == "defaultinattr"
    assert out[KEYPAD] == "LIMITED KEYPAD" and out[CABLE] == "NO"


def test_a_blind_guess_is_replaced_too(flag):
    out, _pending, _ = _fill(filled={CABLE: "YES"}, sources={CABLE: "blind_pick_rule_governed"})
    assert out[CABLE] == "NO"


def test_what_the_customer_typed_this_turn_wins_over_the_default(flag):
    """Review probe 1: the hint stage runs before the default is written, so the customer's answer is not lost."""
    out, _pending, sources = _fill(hints={KEYPAD: "Full Keypad"})
    assert out[KEYPAD] == "FULL KEYPAD" and sources[KEYPAD] == "hint"


def test_a_recommendation_rule_that_applies_now_wins_over_the_default(flag):
    """Review probe 2: tier 2 runs before the default is written."""
    rule = RecommendationRule(rule_name="r", condition_attr_id=1, condition_value="APX N30", target_attr_id=3,
                              recommended_value="FULL KEYPAD")
    out, _pending, sources = _fill(rec_rules=[rule])
    assert out[KEYPAD] == "FULL KEYPAD" and sources[KEYPAD] == "rule"
    out, _pending, sources = _fill(filled={KEYPAD: "NO KEYPAD"}, sources={KEYPAD: "rule"}, rec_rules=[rule])
    assert out[KEYPAD] == "FULL KEYPAD"                          # a pick that differs from the rule is still replaced


def test_when_the_base_model_changes_the_old_defaults_are_replaced(flag):
    """Review probe 3: a default written for the old base model must not outlive it."""
    out, _pending, sources = _fill()
    assert out[KEYPAD] == "LIMITED KEYPAD" and sources[KEYPAD] == "defaultinattr"
    out, _pending, sources = _fill(filled={KEYPAD: out[KEYPAD]}, sources={KEYPAD: "defaultinattr"}, base=CODE2)
    assert out[KEYPAD] == "FULL KEYPAD" and sources[KEYPAD] == "defaultinattr"


def test_a_value_the_customer_or_their_wording_gave_stays(flag):
    for source in ("user", "hint", "auto", "data_table"):
        out, _pending, sources = _fill(filled={ANT: "STANDARD"}, sources={ANT: source})
        assert out[ANT] == "STANDARD" and sources[ANT] == source, source


def test_an_attribute_the_governance_stage_always_asks_gets_no_default(flag):
    out, pending, _ = _fill()
    assert SELECT not in out and SELECT in pending          # a select-model attribute is asked, never defaulted


def test_a_default_stored_as_a_display_name_is_matched(flag):
    rows = [_row(CODE, KEYPAD, "Limited Keypad")]
    out, _pending, _ = _fill(rows=rows)
    assert out[KEYPAD] == "LIMITED KEYPAD"


def test_a_default_that_is_not_an_option_is_not_used(flag):
    out, _pending, sources = _fill(filled={ANT: "STANDARD"}, sources={ANT: "rule"}, rows=[_row(CODE, ANT, "NO SUCH")])
    assert out[ANT] == "STANDARD" and sources[ANT] == "rule"


def test_with_the_flag_off_nothing_changes(flag):
    flag.cpq_base_model_defaults_enabled = False
    out, _pending, sources = _fill(filled={ANT: "STANDARD"}, sources={ANT: "rule"})
    assert out[ANT] == "STANDARD" and sources[ANT] == "rule" and "defaultinattr" not in sources.values()


# --- where the two stages sit -----------------------------------------------------------------------------------
def test_the_stages_sit_where_the_precedence_needs_them():
    names = [f.__name__ for f in coordinator._STAGES]
    assert names.index("stage_base_model_default_clear") == names.index("stage_not_applicable_guard") + 1
    assert names.index("stage_base_model_default_clear") < names.index("stage_already_filled")
    assert names.index("stage_base_model_default_fill") == names.index("stage_satisfied_recommendation") + 1
    assert names.index("stage_base_model_default_fill") < names.index("stage_default_value")
    assert names.index("stage_hint_match") < names.index("stage_base_model_default_fill")


def test_no_real_base_model_means_no_default(flag):
    out, _pending, _ = _fill(filled={ANT: "STANDARD"},
                             sources={ANT: "rule", BASE: "blind_pick_rule_governed"})
    assert out[ANT] == "STANDARD"                               # a guessed base model is not one
    stage = SimpleNamespace()                                   # and none at all
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=ROWS):
        assert bmd.base_model_defaults("", 1, "p", {}) == {} and stage is not None
