"""docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md.

CpqEngine._attribute_depth_ranks / rank_rules_by_specificity: rules whose
condition sits deeper in the rule-proven attribute-gating graph (a
generic, catalog-agnostic stand-in for "product family -> product line ->
product" specificity) execute later, so same-target hiding/recommendation
conflicts resolve deterministically in favor of the more specific rule
instead of whatever order fetch_rules()/fetch_value_rules() happened to
return (neither has an ORDER BY). Made-up attribute/rule names throughout
(mirroring test_cpq_payload_dependency_order.py's convention) except the
one test that replays a real, live-audited conflict shape.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, order: int = 999) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=vn,
        display_label=vn, required=False, default_value="",
        options=_menu("A", "B"), order=order,
    )


def test_depth_chain_root_mid_leaf():
    attrs = [_attr(1, "root"), _attr(2, "mid"), _attr(3, "leaf")]
    rules = [
        HidingRule(rule_name="r1", condition_attr_id=1, condition_value="A",
                   target_attr_id=2),
        HidingRule(rule_name="r2", condition_attr_id=2, condition_value="A",
                   target_attr_id=3),
    ]
    depth = CpqEngine._attribute_depth_ranks(attrs, rules)
    assert depth["root"] == 0
    assert depth["mid"] == 1
    assert depth["leaf"] == 2


def test_depth_diamond_child_is_max_of_two_parents():
    attrs = [_attr(1, "left"), _attr(2, "right"), _attr(3, "child")]
    rules = [
        HidingRule(rule_name="r1", condition_attr_id=1, condition_value="A",
                   target_attr_id=3),
        HidingRule(rule_name="r2", conditions=[(2, "A")],
                   condition_attr_id=0, condition_value="",
                   target_attr_id=3),
        # right is itself gated by left, so right's depth (1) > left's (0);
        # child must take the MAX (right's branch), not the first-seen edge.
        HidingRule(rule_name="r3", condition_attr_id=1, condition_value="A",
                   target_attr_id=2),
    ]
    depth = CpqEngine._attribute_depth_ranks(attrs, rules)
    assert depth["left"] == 0
    assert depth["right"] == 1
    assert depth["child"] == 2  # max(left=0, right=1) + 1


def test_depth_cycle_does_not_hang_and_never_gets_depth_zero():
    attrs = [_attr(1, "a"), _attr(2, "b"), _attr(3, "root")]
    rules = [
        HidingRule(rule_name="r1", condition_attr_id=1, condition_value="A",
                   target_attr_id=2),
        HidingRule(rule_name="r2", condition_attr_id=2, condition_value="A",
                   target_attr_id=1),
    ]
    depth = CpqEngine._attribute_depth_ranks(attrs, rules)
    assert depth["root"] == 0
    # a/b form a genuine cycle: neither ever reaches in-degree 0. Must not
    # be silently promoted to depth 0 (would make an ambiguous rule "most
    # trusted") and must not hang.
    assert depth["a"] > 0
    assert depth["b"] > 0


def test_depth_script_backed_rule_contributes_no_edge():
    attrs = [_attr(1, "gate"), _attr(2, "scripted_target")]
    rules = [
        HidingRule(rule_name="scripted", condition_attr_id=0, condition_value="",
                   target_attr_id=2, script="return TRUE;"),
    ]
    depth = CpqEngine._attribute_depth_ranks(attrs, rules)
    # No declarative condition/conditions -> no edge -> both stay at the
    # zero-in-degree root depth.
    assert depth["gate"] == 0
    assert depth["scripted_target"] == 0


def test_depth_no_rules_at_all_is_pure_zero_no_behavior_change():
    attrs = [_attr(1, "a"), _attr(2, "b")]
    depth = CpqEngine._attribute_depth_ranks(attrs, [])
    assert depth == {"a": 0, "b": 0}


def test_hiding_conflict_resolves_to_narrow_rule_regardless_of_input_order():
    """The actual fix: two HidingRules disagree on the same target — one
    gated on a broad/shallow condition, one on a narrow/deep condition
    (mirrors the real Hardware-Version-gates-Product-Selection shape).
    Both raw input orders must converge on the SAME (narrow-wins) result."""
    attrs = [_attr(1, "broad_gate"), _attr(2, "narrow_gate", order=1),
             _attr(3, "target", order=2)]
    # narrow_gate is itself gated by broad_gate, so narrow_gate's condition
    # is structurally deeper/more specific than broad_gate's.
    depth_setup_rule = HidingRule(
        rule_name="establish depth", condition_attr_id=1, condition_value="A",
        target_attr_id=2)
    broad_hides = HidingRule(
        rule_name="broad hides target", condition_attr_id=1, condition_value="A",
        target_attr_id=3, hide=True)
    narrow_shows = HidingRule(
        rule_name="narrow un-hides target", condition_attr_id=2, condition_value="A",
        target_attr_id=3, hide=False)

    for raw_order in ([broad_hides, narrow_shows, depth_setup_rule],
                       [narrow_shows, depth_setup_rule, broad_hides]):
        eng = CpqEngine()
        ranked_hiding, _rec, _con = eng.rank_rules_by_specificity(attrs, raw_order, [], [])
        filled = {"broad_gate": "A", "narrow_gate": "A"}
        visible, _msgs, hidden_vns = eng.apply_hiding_rules(
            attrs, filled, ranked_hiding, bml_eval=None)
        assert "target" not in hidden_vns, (
            "the more specific (narrow_gate-conditioned) rule must win and "
            "keep target visible, regardless of raw input order"
        )


def test_recommendation_conflict_resolves_to_specific_value_regardless_of_input_order():
    attrs = [_attr(1, "broad_gate"), _attr(2, "narrow_gate", order=1),
              _attr(3, "target", order=2)]
    depth_setup_rule = HidingRule(
        rule_name="establish depth", condition_attr_id=1, condition_value="A",
        target_attr_id=2)
    broad_rec = RecommendationRule(
        rule_name="broad recommends X", condition_attr_id=1, condition_value="A",
        target_attr_id=3, recommended_value="A")
    narrow_rec = RecommendationRule(
        rule_name="narrow recommends Y", condition_attr_id=2, condition_value="A",
        target_attr_id=3, recommended_value="B")

    for raw_order in ([broad_rec, narrow_rec], [narrow_rec, broad_rec]):
        eng = CpqEngine()
        _hide, ranked_rec, _con = eng.rank_rules_by_specificity(
            attrs, [depth_setup_rule], raw_order, [])
        filled = {"broad_gate": "A", "narrow_gate": "A"}
        new_fills = eng.apply_recommendation_rules(attrs, filled, ranked_rec, bml_eval=None)
        assert new_fills["target"][0] == "B", (
            "the more specific (narrow_gate-conditioned) recommendation "
            "must win regardless of raw input order"
        )


class _FakeBmlEval:
    """Minimal stand-in for BmlEvaluator — only the two methods
    apply_recommendation_rules actually calls for script-backed rules.
    Both real rules being replayed here are declarative-value-with-a-
    condition_script or pure-value-script, never Tier-2/LLM, so a plain
    string-match stub is faithful without needing the real evaluator."""

    def allowed_values_for_script(self, script, variables, cache_id=None):
        if 'return "BASELINE RELEASE"' in script:
            return ["BASELINE RELEASE"]
        return None

    def condition_holds(self, script, variables, cache_id=None):
        if "is_eligible_customer" in script:
            return variables.get("is_eligible_customer") == "YES"
        return None


def test_real_baseline_release_shape_latest_release_wins_for_eligible_customer():
    """Replays the live-audited conflict on baselineReleaseSW_astro
    (workspace 39004) using the EXACT field shape production has (verified
    directly against the running container): both rules have
    condition_attr_id=0 and conditions=None — 'Set default to Baseline
    Release' is a pure VALUE SCRIPT with no separate condition_script at
    all (tier 0), 'Default to Latest Release if not NA/fed customer' is a
    declarative recommended_value gated by a condition_script (tier 1).
    An earlier version of this test set condition_attr_id=1 on the latter,
    which accidentally routed it through the tier-2 declarative-depth path
    instead of the tier-1 condition_script path it needed to exercise —
    masking a real bug where both rules landed in the same "unrankable"
    bucket and tied, preserving arbitrary order. For an eligible (non-NA,
    non-federal) customer both are satisfied simultaneously in production;
    today's arbitrary rule-list order decides the winner."""
    attrs = [_attr(1, "is_eligible_customer"), _attr(2, "baseline_release_sw")]
    unconditional_baseline = RecommendationRule(
        rule_name="Set default to Baseline Release for Baseline Release SW",
        condition_attr_id=0, condition_value="",
        target_attr_id=2, script='return "BASELINE RELEASE";')
    conditional_latest = RecommendationRule(
        rule_name="Default to Latest Release if not NA/fed customer",
        condition_attr_id=0, condition_value="",
        target_attr_id=2, recommended_value="LATEST RELEASE",
        condition_script='if (is_eligible_customer<>"NO") { return true; } return false;')

    for raw_order in ([unconditional_baseline, conditional_latest],
                       [conditional_latest, unconditional_baseline]):
        eng = CpqEngine()
        _hide, ranked_rec, _con = eng.rank_rules_by_specificity(attrs, [], raw_order, [])
        filled = {"is_eligible_customer": "YES"}
        new_fills = eng.apply_recommendation_rules(
            attrs, filled, ranked_rec, bml_eval=_FakeBmlEval())
        assert new_fills["baseline_release_sw"][0] == "LATEST RELEASE", (
            "the conditional, provably-specific rule must beat the "
            "unconditional fallback once its condition is genuinely met"
        )


def test_constraint_rules_pass_through_unchanged():
    from aryx.cpq.state import ConstraintRule
    attrs = [_attr(1, "a")]
    con_rules = [
        ConstraintRule(rule_name="c1", condition_attr_id=0, condition_value="",
                       target_attr_id=1, allowed_values=["A"]),
        ConstraintRule(rule_name="c2", condition_attr_id=0, condition_value="",
                       target_attr_id=1, allowed_values=["B"]),
    ]
    eng = CpqEngine()
    _hide, _rec, ranked_con = eng.rank_rules_by_specificity(attrs, [], [], con_rules)
    assert ranked_con is con_rules
