"""build_payload: dependency-aware payload key ordering.

Live finding (docs/APX_Next_RootCause_And_Fix_Report — sequencing issue):
bm_config_attr.order_number (ConfigAttr.order), the field the pre-existing
sort relied on exclusively, is a catalog UI/display-layout field, not a
rule-dependency sequence. Confirmed live in the APX Next catalog: Product
(order_number=26) sorted far AHEAD of Hardware Version (order_number=128)
despite 3 independent rules proving Product's own value is gated by
Hardware Version. This file uses made-up attribute/rule names (not the
real APX Next ones) to prove the fix is catalog-agnostic, not tuned to one
export's data.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _attrs_with_inverted_order():
    """Mirrors the real APX Next contradiction: the attr that gates another
    (gate) has a HIGHER order_number than the attr it gates (gated) — the
    exact inversion that made order_number-only sorting wrong."""
    return [
        ConfigAttr(entity_id=10, source_id=10, variable_name="gate",
                   display_label="Gate Attr", required=False, default_value="",
                   options=_menu("A", "B"), order=128),
        ConfigAttr(entity_id=20, source_id=20, variable_name="gated",
                   display_label="Gated Attr", required=False, default_value="",
                   options=_menu("X", "Y"), order=26),
        ConfigAttr(entity_id=30, source_id=30, variable_name="unrelated",
                   display_label="Unrelated Attr", required=False, default_value="",
                   options=_menu("P", "Q"), order=5),
    ]


def test_without_rules_falls_back_to_order_number_exact_prior_behavior():
    attrs = _attrs_with_inverted_order()
    filled = {"gate": "A", "gated": "X", "unrelated": "P"}
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs,
    )["configData"]
    # No rules supplied -> pure order_number sort, gated (26) before gate (128)
    assert list(payload.keys()) == ["unrelated", "gated", "gate"]


def test_with_rules_gate_is_placed_before_gated_despite_order_number():
    attrs = _attrs_with_inverted_order()
    filled = {"gate": "A", "gated": "X", "unrelated": "P"}
    rules = [
        ConstraintRule(
            rule_name="Restrict gated based on gate",
            condition_attr_id=10, condition_value="A",
            target_attr_id=20, allowed_values=["X"],
        ),
    ]
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs, rules=rules,
    )["configData"]
    keys = list(payload.keys())
    assert keys.index("gate") < keys.index("gated"), (
        "gate must precede gated once a rule proves the dependency, "
        "regardless of order_number"
    )
    # unrelated has no dependency edge either way -> tie-broken by order_number (5, lowest)
    assert keys[0] == "unrelated"


def test_hiding_rule_dependency_also_respected():
    attrs = _attrs_with_inverted_order()
    filled = {"gate": "A", "gated": "X", "unrelated": "P"}
    rules = [
        HidingRule(
            rule_name="Hide gated unless gate answered",
            condition_attr_id=10, condition_value="A",
            target_attr_id=20, hide=False,
        ),
    ]
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs, rules=rules,
    )["configData"]
    keys = list(payload.keys())
    assert keys.index("gate") < keys.index("gated")


def test_declarative_multi_condition_list_also_respected():
    attrs = _attrs_with_inverted_order() + [
        ConfigAttr(entity_id=40, source_id=40, variable_name="gate2",
                   display_label="Second Gate", required=False, default_value="",
                   options=_menu("C", "D"), order=200),
    ]
    filled = {"gate": "A", "gate2": "C", "gated": "X", "unrelated": "P"}
    rules = [
        ConstraintRule(
            rule_name="Restrict gated based on gate AND gate2",
            condition_attr_id=0, condition_value="",
            target_attr_id=20, allowed_values=["X"],
            conditions=[(10, "A"), (40, "C")],
        ),
    ]
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs, rules=rules,
    )["configData"]
    keys = list(payload.keys())
    assert keys.index("gate") < keys.index("gated")
    assert keys.index("gate2") < keys.index("gated")


def test_cycle_never_drops_a_key():
    """Two rules that mutually gate each other (a genuine rule-authoring
    conflict, never expected but must not crash or lose data) fall back to
    order_number for the tied pair rather than looping or dropping keys."""
    attrs = _attrs_with_inverted_order()
    filled = {"gate": "A", "gated": "X", "unrelated": "P"}
    rules = [
        ConstraintRule(rule_name="A gates B", condition_attr_id=10,
                        condition_value="A", target_attr_id=20, allowed_values=["X"]),
        ConstraintRule(rule_name="B gates A", condition_attr_id=20,
                        condition_value="X", target_attr_id=10, allowed_values=["A"]),
    ]
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs, rules=rules,
    )["configData"]
    assert set(payload.keys()) == {"gate", "gated", "unrelated"}


def test_script_backed_rule_has_no_condition_attr_id_falls_back_gracefully():
    """A script-backed rule (condition_attr_id==0, no declarative conditions)
    contributes no edge — same as an attr with no rule-derived ordering at
    all, never guessed, never crashes."""
    attrs = _attrs_with_inverted_order()
    filled = {"gate": "A", "gated": "X", "unrelated": "P"}
    rules = [
        ConstraintRule(
            rule_name="Script-backed constraint",
            condition_attr_id=0, condition_value="",
            target_attr_id=20, allowed_values=[],
            script="retVal = string[]; return retVal;",
        ),
    ]
    payload = CpqEngine().build_payload(
        filled, {k: "user" for k in filled}, {}, attrs, rules=rules,
    )["configData"]
    # No edge contributed -> falls back to order_number for "gated", same
    # as the no-rules-supplied case
    assert list(payload.keys()) == ["unrelated", "gated", "gate"]
