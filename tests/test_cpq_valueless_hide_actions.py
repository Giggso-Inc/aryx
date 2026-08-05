"""docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md

_load_value_rules previously dropped ANY declarative action (function_id=-1)
whose value1 was NULL, before even inspecting set_type -- confirmed live via
a cross-catalog audit (1,096 such actions across 421 rules in 4 ingested
catalogs) that this silently discarded a real class of BM-authored "hide"
rules authored outside rule_type=11 (e.g. "Associated rec rule to Hide
Frequency Band for Single Band"), since hiding needs no value1 to assign.

Phase 1 scope: set_type in (1, 3) + function_id=-1 + value1 IS NULL -> load
as a HidingRule. set_type in (2, -1) are deliberately left unchanged --
sampled real rule names in those buckets are genuinely mixed (some "Show...",
some "Set X to blank", some pure format/range validation unrelated to
hiding) and were never guessed without separate confirmation (D2).
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, MenuOption, RecommendationRule


class _FakeRdb:
    """Minimal double for exactly what _load_value_rules/_load_rule_join_data
    need -- (rule_id, attr_id, action_type, value1, function_id, set_type,
    comments) action rows plus the matching condition/value-rule fetches."""

    def __init__(self, value_rules, inputs=(), actions=(), scripts=None):
        self._value_rules = value_rules
        self._inputs = list(inputs)
        self._actions = list(actions)
        self._scripts = scripts or {}

    def fetch_value_rules(self, workspace_id, catalog_prefix=""):
        return self._value_rules

    def fetch_rule_inputs(self, workspace_id, catalog_prefix=""):
        # (rule_id, attr_id, value1, operator1) -- 3-tuple inputs default to
        # operator "4" ("="), same convention as
        # test_cpq_declarative_condition_operators.py.
        return [
            row if len(row) == 4 else (*row, "4")
            for row in self._inputs
        ]

    def fetch_rule_actions(self, workspace_id, catalog_prefix=""):
        return self._actions

    def fetch_marked_attrs(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_rule_chain_links(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_function_scripts(self, workspace_id, catalog_prefix=""):
        return self._scripts

    def fetch_rules(self, workspace_id, rule_type, catalog_prefix="", active_only=False):
        return []


def _load(fake_rdb):
    with patch("aryx.cpq.engine.get_cpq_rdb", return_value=fake_rdb), \
         patch("aryx.cpq.engine.IngestQuestionStore", side_effect=RuntimeError("no db in unit test")):
        return CpqEngine()._load_value_rules(1, "")


def test_valueless_declarative_action_becomes_hiding_rule_set_type_3():
    """Replays the real "Associated rec rule to Hide Frequency Band for
    Single Band" shape: rule_type=1 (not 11), condition on
    productSelectionProduct_all == "APX NEXT SINGLE", action has NO value1,
    set_type=3."""
    fake_rdb = _FakeRdb(
        value_rules=[(100, 100, "Hide Frequency Band for Single Band", "1", -1)],
        inputs=[(100, 1, "APX NEXT SINGLE")],
        actions=[(100, 2, 1, None, -1, 3, "System recommendation")],
    )
    rec_rules, con_rules, validation_rules, hiding_rules = _load(fake_rdb)
    assert rec_rules == []
    assert con_rules == []
    assert validation_rules == []
    assert len(hiding_rules) == 1
    rule = hiding_rules[0]
    assert isinstance(rule, HidingRule)
    assert rule.target_attr_id == 2
    assert rule.condition_attr_id == 1
    assert rule.condition_value == "APX NEXT SINGLE"
    assert rule.hide is True
    assert rule.script is None


def test_valueless_hiding_rule_carries_real_condition_operator():
    """The new HidingRule must thread condition_operator through like its
    ConstraintRule/RecommendationRule siblings -- not silently default to
    "=" when the real condition uses e.g. "<>" (docs/CPQ_DECLARATIVE_
    CONDITION_OPERATOR_PLAN_2026_08_05.md)."""
    fake_rdb = _FakeRdb(
        value_rules=[(150, 150, "Hide X for non-Federal", "1", -1)],
        inputs=[(150, 1, "FEDERAL", "3")],
        actions=[(150, 2, 1, None, -1, 3, "System recommendation")],
    )
    _rec, _con, _val, hiding_rules = _load(fake_rdb)
    assert len(hiding_rules) == 1
    assert hiding_rules[0].condition_operator == "3"


def test_valueless_declarative_action_becomes_hiding_rule_set_type_1():
    fake_rdb = _FakeRdb(
        value_rules=[(200, 200, "Hide Y if X selected", "2", -1)],
        inputs=[(200, 1, "X")],
        actions=[(200, 3, 1, None, -1, 1, "System recommendation")],
    )
    _rec, _con, _val, hiding_rules = _load(fake_rdb)
    assert len(hiding_rules) == 1
    assert hiding_rules[0].target_attr_id == 3


def test_valueless_declarative_action_with_script_condition_carries_script():
    """A value-less hide action whose RULE condition is itself a script
    (condition_function_id != -1) must gate via HidingRule.script, same
    convention load_hiding_rules already uses for script-backed hides."""
    fake_rdb = _FakeRdb(
        value_rules=[(300, 300, "Hide Z if script says so", "1", 999)],
        actions=[(300, 4, 1, None, -1, 3, "System recommendation")],
        scripts={999: 'if (region<>"NA") { return true; } return false;'},
    )
    _rec, _con, _val, hiding_rules = _load(fake_rdb)
    assert len(hiding_rules) == 1
    rule = hiding_rules[0]
    assert rule.target_attr_id == 4
    assert rule.script == 'if (region<>"NA") { return true; } return false;'
    assert rule.conditions is None


def test_valueless_action_set_type_2_still_dropped_unchanged():
    """set_type=2's real rule names are genuinely mixed (some "Show...",
    some "Set X to blank") -- deliberately NOT guessed as hide (D2). Must
    stay dropped exactly as before this fix."""
    fake_rdb = _FakeRdb(
        value_rules=[(400, 400, "Show SIM Card Selection only for Enhanced", "2", -1)],
        inputs=[(400, 1, "ENHANCED")],
        actions=[(400, 5, 1, None, -1, 2, "System recommendation")],
    )
    rec_rules, con_rules, _val, hiding_rules = _load(fake_rdb)
    assert hiding_rules == []
    assert rec_rules == []
    assert con_rules == []


def test_valueless_action_set_type_minus1_still_dropped_unchanged():
    """set_type=-1's real rule names are mostly format/range validation
    unrelated to hiding ("Restrict value of Astro System Id to 4 hexadecimal
    chars") -- out of scope for this fix, must stay dropped."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Restrict Astro System Id value", "2", -1)],
        inputs=[(500, 1, "X")],
        actions=[(500, 6, 1, None, -1, -1, "System recommendation")],
    )
    rec_rules, con_rules, _val, hiding_rules = _load(fake_rdb)
    assert hiding_rules == []
    assert rec_rules == []
    assert con_rules == []


def test_normal_recommendation_unaffected():
    """A real value1 must still route through the existing recommend
    branch, completely unaffected by the new hide_targets logic."""
    fake_rdb = _FakeRdb(
        value_rules=[(600, 600, "Default to Latest Release", "1", -1)],
        inputs=[(600, 1, "US")],
        actions=[(600, 7, 1, "LATEST RELEASE", -1, 3, "System recommendation")],
    )
    rec_rules, con_rules, _val, hiding_rules = _load(fake_rdb)
    assert hiding_rules == []
    assert con_rules == []
    assert len(rec_rules) == 1
    rule = rec_rules[0]
    assert isinstance(rule, RecommendationRule)
    assert rule.target_attr_id == 7
    assert rule.recommended_value == "LATEST RELEASE"


def test_normal_constraint_unaffected():
    """A real value1 with set_type=-1 must still route through the existing
    restrict branch, completely unaffected by the new hide_targets logic."""
    fake_rdb = _FakeRdb(
        value_rules=[(700, 700, "Constrain Carrier Selection", "2", -1)],
        inputs=[(700, 1, "US")],
        actions=[(700, 8, 1, "ATT~VERIZON", -1, -1, "System recommendation")],
    )
    rec_rules, con_rules, _val, hiding_rules = _load(fake_rdb)
    assert hiding_rules == []
    assert rec_rules == []
    assert len(con_rules) == 1
    rule = con_rules[0]
    assert isinstance(rule, ConstraintRule)
    assert rule.target_attr_id == 8
    assert rule.allowed_values == ["ATT", "VERIZON"]


def test_multiple_targets_same_rule_mixed_hide_and_recommend():
    """One rule can have several action rows -- some value-less (hide),
    some with a real value (recommend/constrain) -- each classified
    independently by its own row, not by the rule as a whole."""
    fake_rdb = _FakeRdb(
        value_rules=[(800, 800, "Mixed rule", "1", -1)],
        inputs=[(800, 1, "X")],
        actions=[
            (800, 9, 1, None, -1, 3, "System recommendation"),
            (800, 10, 1, "SOME VALUE", -1, 3, "System recommendation"),
        ],
    )
    rec_rules, con_rules, _val, hiding_rules = _load(fake_rdb)
    assert len(hiding_rules) == 1
    assert hiding_rules[0].target_attr_id == 9
    assert len(rec_rules) == 1
    assert rec_rules[0].target_attr_id == 10
    assert con_rules == []


def test_load_recommendation_and_constraint_rules_arity_unchanged():
    """Deliberately still a 2-tuple -- monkeypatched with a bare (rec, con)
    stub across ~20 sites in the test suite; the value-less hiding subset
    is folded into load_hiding_rules() instead (see next test), not here."""
    fake_rdb = _FakeRdb(
        value_rules=[(900, 900, "Hide W", "1", -1)],
        inputs=[(900, 1, "X")],
        actions=[(900, 11, 1, None, -1, 3, "System recommendation")],
    )
    with patch("aryx.cpq.engine.get_cpq_rdb", return_value=fake_rdb), \
         patch("aryx.cpq.engine.IngestQuestionStore", side_effect=RuntimeError("no db")):
        result = CpqEngine().load_recommendation_and_constraint_rules(1, "")
    assert result == ([], [])


def test_load_hiding_rules_merges_in_the_valueless_subset():
    """load_hiding_rules() -- the method every real caller already uses --
    must return the complete hiding rule set, including the value-less-
    action subset _load_value_rules classifies, with zero call-site
    changes needed anywhere."""
    fake_rdb = _FakeRdb(
        value_rules=[(900, 900, "Hide W", "1", -1)],
        inputs=[(900, 1, "X")],
        actions=[(900, 11, 1, None, -1, 3, "System recommendation")],
    )
    with patch("aryx.cpq.engine.get_cpq_rdb", return_value=fake_rdb), \
         patch("aryx.cpq.engine.IngestQuestionStore", side_effect=RuntimeError("no db")):
        hiding_rules = CpqEngine().load_hiding_rules(1, "")
    assert len(hiding_rules) == 1
    assert hiding_rules[0].target_attr_id == 11
    assert hiding_rules[0].rule_name == "Hide W"


# ---- End-to-end: a loaded value-less-action rule actually hides ----------
#
# The tests above only prove the LOADING shape is right (HidingRule
# objects with the right fields). None of them prove a rule loaded this
# way actually hides its target when run through apply_hiding_rules --
# closing that gap here, replaying the real "Associated rec rule to Hide
# Frequency Band for Single Band" shape end-to-end.

def _attr(entity_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=vn,
        display_label=vn, required=False, default_value="",
        options=[MenuOption(item_value="X", display_name="X", order=1)],
    )


def test_loaded_valueless_hiding_rule_actually_hides_its_target():
    attrs = [
        _attr(1, "productSelectionProduct_all"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro"),
    ]
    rules = [
        HidingRule(
            rule_name="Associated rec rule to Hide Frequency Band for Single Band",
            condition_attr_id=1, condition_value="APX NEXT SINGLE BAND",
            target_attr_id=2, hide=True,
            conditions=[(1, "APX NEXT SINGLE BAND", "4")],
        ),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {"productSelectionProduct_all": "APX NEXT SINGLE BAND"}, rules, bml_eval=None)
    assert "modelSelectionFrequencyBandMsl_astro" in hidden_vns


def test_loaded_valueless_hiding_rule_does_not_fire_for_a_different_product():
    attrs = [
        _attr(1, "productSelectionProduct_all"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro"),
    ]
    rules = [
        HidingRule(
            rule_name="Associated rec rule to Hide Frequency Band for Single Band",
            condition_attr_id=1, condition_value="APX NEXT SINGLE BAND",
            target_attr_id=2, hide=True,
            conditions=[(1, "APX NEXT SINGLE BAND", "4")],
        ),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {"productSelectionProduct_all": "APX NEXT ALL BAND"}, rules, bml_eval=None)
    assert "modelSelectionFrequencyBandMsl_astro" not in hidden_vns


def test_full_pipeline_load_then_apply_hides_the_target():
    """The most faithful proof: build the HidingRule via the ACTUAL
    _load_value_rules classification path (not hand-constructed), then feed
    that real output into apply_hiding_rules -- covers the full load ->
    apply pipeline for this new code path in one test."""
    fake_rdb = _FakeRdb(
        value_rules=[(100, 100, "Hide Frequency Band for Single Band", "1", -1)],
        inputs=[(100, 1, "APX NEXT SINGLE BAND")],
        actions=[(100, 2, 1, None, -1, 3, "System recommendation")],
    )
    with patch("aryx.cpq.engine.get_cpq_rdb", return_value=fake_rdb), \
         patch("aryx.cpq.engine.IngestQuestionStore", side_effect=RuntimeError("no db")):
        hiding_rules = CpqEngine().load_hiding_rules(1, "")

    attrs = [
        _attr(1, "productSelectionProduct_all"),
        _attr(2, "modelSelectionFrequencyBandMsl_astro"),
    ]
    eng = CpqEngine()
    _visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        attrs, {"productSelectionProduct_all": "APX NEXT SINGLE BAND"}, hiding_rules, bml_eval=None)
    assert "modelSelectionFrequencyBandMsl_astro" in hidden_vns
