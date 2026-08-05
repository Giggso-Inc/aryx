"""docs/CPQ_CONDITIONAL_REQUIRED_RULE_PLAN_2026_08_05.md

ValidationRule (a message-only rule with no value action -- "condition true
-> show this message, no value change") was previously loaded ONLY when its
condition was a BML script. Confirmed via a 4-catalog audit that 138/150
real "set_type=-1, no value1" declarative action rows carry a genuine,
non-boilerplate message -- e.g. "Restrict Number Of Seats between 1 and 12"
-> "Number Of Seats must be between 1 and 12", gated declaratively
(operators "1"/"5" on the target's own value). This was explicitly
anticipated but deferred in _load_value_rules pending exactly this
confirmation. This module tests the now-widened loading path and
apply_validation_rules' new declarative branch.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, ValidationRule


class _FakeRdb:
    """Same minimal double as test_cpq_valueless_hide_actions.py."""

    def __init__(self, value_rules, inputs=(), actions=(), scripts=None):
        self._value_rules = value_rules
        self._inputs = list(inputs)
        self._actions = list(actions)
        self._scripts = scripts or {}

    def fetch_value_rules(self, workspace_id, catalog_prefix=""):
        return self._value_rules

    def fetch_rule_inputs(self, workspace_id, catalog_prefix=""):
        return [row if len(row) == 4 else (*row, "4") for row in self._inputs]

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


def _attr(entity_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=vn,
        display_label=vn, required=False, default_value="",
        options=[MenuOption(item_value="X", display_name="X", order=1)],
    )


# ---- Loading: declarative message-only actions now produce ValidationRule -

def test_declarative_message_only_action_becomes_validation_rule():
    """Replays a clean, non-colliding declarative message-only shape: one
    condition row, one value-less action carrying the real message."""
    fake_rdb = _FakeRdb(
        value_rules=[(100, 100, "Restrict Astro System Id value to have at least 1 non-zero char", "2", -1)],
        inputs=[(100, 1, "0000")],
        actions=[(100, 1, 1, None, -1, -1, "Astro System Id cannot be all zeros")],
    )
    rec_rules, con_rules, validation_rules, hiding_rules = _load(fake_rdb)
    assert rec_rules == []
    assert con_rules == []
    assert hiding_rules == []
    assert len(validation_rules) == 1
    rule = validation_rules[0]
    assert isinstance(rule, ValidationRule)
    assert rule.target_attr_id == 1
    assert rule.message == "Astro System Id cannot be all zeros"
    assert rule.condition_script is None
    assert rule.conditions == [(1, "0000", "4")]


def test_same_attribute_operator_collision_is_excluded():
    """docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md --
    replays the real "Restrict Number Of Seats between 1 and 12" shape:
    two condition rows on the SAME attribute with DIFFERENT operators
    (< 1 and > 12). evaluate_declarative_conditions cannot yet evaluate
    this correctly (it would only ever check < 1, silently dropping the
    > 12 bound) -- confirmed catalog-wide that no single combining rule
    is safe for every such shape yet, so this must be excluded entirely
    rather than loaded with a guessed combining rule."""
    fake_rdb = _FakeRdb(
        value_rules=[(100, 100, "Restrict Number Of Seats between 1 and 12", "2", -1)],
        inputs=[(100, 1, "1", "1"), (100, 1, "12", "5")],
        actions=[(100, 1, 1, None, -1, -1, "Number Of Seats must be between 1 and 12")],
    )
    rec_rules, con_rules, validation_rules, hiding_rules = _load(fake_rdb)
    assert validation_rules == []
    assert rec_rules == con_rules == hiding_rules == []


def test_same_attribute_same_operator_is_not_a_collision():
    """A genuine OR-list (same attribute, SAME operator repeated) must
    still load normally -- only DIFFERENT operators on the same attribute
    are excluded."""
    fake_rdb = _FakeRdb(
        value_rules=[(150, 150, "Some OR-list validation", "2", -1)],
        inputs=[(150, 1, "A", "4"), (150, 1, "B", "4")],
        actions=[(150, 2, 1, None, -1, -1, "Invalid selection")],
    )
    _rec, _con, validation_rules, _hide = _load(fake_rdb)
    assert len(validation_rules) == 1
    assert validation_rules[0].conditions == [(1, "A", "4"), (1, "B", "4")]


def test_operator_collision_across_different_attributes_is_not_blocked():
    """The collision check is scoped to a SINGLE attribute -- different
    attributes each checked with their own (possibly different) operator
    is the normal, already-correct AND-across-attributes case and must
    not be excluded."""
    fake_rdb = _FakeRdb(
        value_rules=[(160, 160, "Cross-attribute condition", "2", -1)],
        inputs=[(160, 1, "X", "4"), (160, 2, "5", "1")],
        actions=[(160, 3, 1, None, -1, -1, "Invalid selection")],
    )
    _rec, _con, validation_rules, _hide = _load(fake_rdb)
    assert len(validation_rules) == 1


def test_condition_has_operator_collision_helper_directly():
    assert CpqEngine._condition_has_operator_collision([(1, "1", "1"), (1, "12", "5")]) is True
    assert CpqEngine._condition_has_operator_collision([(1, "A", "4"), (1, "B", "4")]) is False
    assert CpqEngine._condition_has_operator_collision([(1, "A", "4"), (2, "B", "1")]) is False
    assert CpqEngine._condition_has_operator_collision([]) is False


def test_declarative_validation_rule_with_different_target_than_condition():
    """Replays "Restrict blank for Sales Approver if Is provisioning =
    yes": condition on a DIFFERENT attribute than the target."""
    fake_rdb = _FakeRdb(
        value_rules=[(200, 200, "Restrict blank for Sales Approver if Is provisioning = yes", "2", -1)],
        inputs=[(200, 5, "YES")],
        actions=[(200, 6, 1, None, -1, -1, "Input required")],
    )
    _rec, _con, validation_rules, _hide = _load(fake_rdb)
    assert len(validation_rules) == 1
    rule = validation_rules[0]
    assert rule.target_attr_id == 6
    assert rule.condition_attr_id == 5
    assert rule.condition_value == "YES"
    assert rule.message == "Input required"


def test_boilerplate_system_recommendation_still_excluded():
    """"System recommendation" is BM's own generic default -- must still
    never become a ValidationRule, declarative or not."""
    fake_rdb = _FakeRdb(
        value_rules=[(300, 300, "Some rule", "2", -1)],
        inputs=[(300, 1, "X")],
        actions=[(300, 2, 1, None, -1, -1, "System recommendation")],
    )
    _rec, _con, validation_rules, _hide = _load(fake_rdb)
    assert validation_rules == []


def test_no_comment_declarative_action_produces_nothing():
    """A value-less declarative action with NO comment at all (e.g. the
    real "Constrain Carrier Selection Maximum..." shape) has nothing to
    build a message from -- must stay unclassified, not guessed."""
    fake_rdb = _FakeRdb(
        value_rules=[(400, 400, "Constrain Carrier Selection Maximum", "2", -1)],
        inputs=[(400, 1, "X")],
        actions=[(400, 2, 1, None, -1, -1, None)],
    )
    rec_rules, con_rules, validation_rules, hiding_rules = _load(fake_rdb)
    assert rec_rules == con_rules == validation_rules == hiding_rules == []


def test_script_gated_validation_rule_unaffected():
    """The pre-existing script-gated shape (e.g. "Constrain video
    devices") must be completely unchanged."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Constrain video devices", "2", 999)],
        actions=[(500, 1, 1, None, -1, -1, "Please enter a qty in multiple of 25.")],
        scripts={999: 'if (fmod(qty,25)<>0) { return true; } return false;'},
    )
    _rec, _con, validation_rules, _hide = _load(fake_rdb)
    assert len(validation_rules) == 1
    rule = validation_rules[0]
    assert rule.condition_script == 'if (fmod(qty,25)<>0) { return true; } return false;'
    assert rule.conditions is None
    assert rule.condition_attr_id == 0


# ---- apply_validation_rules: declarative branch -----------------------

def test_apply_validation_rules_fires_declarative_condition():
    # Single-condition shape (the only shape the loader will ever actually
    # produce post-collision-exclusion -- see
    # docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md).
    attrs = [_attr(1, "numberOfSeats_astro")]
    rules = [
        ValidationRule(
            rule_name="Require at least 1 seat",
            target_attr_id=1,
            message="At least 1 seat is required",
            conditions=[(1, "1", "1")],
        ),
    ]
    eng = CpqEngine()
    warnings = eng.apply_validation_rules(attrs, {"numberOfSeats_astro": "0"}, rules, bml_eval=None)
    assert warnings.get("numberOfSeats_astro") == "At least 1 seat is required"


def test_apply_validation_rules_does_not_fire_when_condition_false():
    attrs = [_attr(1, "numberOfSeats_astro")]
    rules = [
        ValidationRule(
            rule_name="Require at least 1 seat",
            target_attr_id=1,
            message="At least 1 seat is required",
            conditions=[(1, "1", "1")],
        ),
    ]
    eng = CpqEngine()
    warnings = eng.apply_validation_rules(attrs, {"numberOfSeats_astro": "5"}, rules, bml_eval=None)
    assert "numberOfSeats_astro" not in warnings


def test_apply_validation_rules_declarative_needs_no_bml_eval():
    """Declarative validation rules must fire even with bml_eval=None --
    unlike script-gated rules, they need no BML evaluator at all (same
    precedent as apply_hiding_rules' declarative branch)."""
    attrs = [_attr(1, "salesApprover_astro"), _attr(2, "isProvisioning_astro")]
    rules = [
        ValidationRule(
            rule_name="Restrict blank for Sales Approver if Is provisioning = yes",
            target_attr_id=1,
            message="Input required",
            condition_attr_id=2, condition_value="YES",
            conditions=[(2, "YES", "4")],
        ),
    ]
    eng = CpqEngine()
    warnings = eng.apply_validation_rules(
        attrs, {"isProvisioning_astro": "YES"}, rules, bml_eval=None)
    assert warnings.get("salesApprover_astro") == "Input required"


def test_apply_validation_rules_script_gated_unaffected():
    attrs = [_attr(1, "qty_astro")]
    rules = [
        ValidationRule(
            rule_name="Constrain video devices",
            target_attr_id=1,
            message="Please enter a qty in multiple of 25.",
            condition_script="dummy",
        ),
    ]
    eng = CpqEngine()
    # bml_eval=None must still skip the script-gated rule (unchanged
    # behavior), NOT fall through to a declarative evaluation.
    warnings = eng.apply_validation_rules(attrs, {"qty_astro": "26"}, rules, bml_eval=None)
    assert warnings == {}
