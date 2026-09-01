"""docs/CPQ_AUTO_FILL_TIER2_PREFETCH_GAP_PLAN_2026_08_10.md

evaluate_rules_loop already prefetches Tier-2 for rec_rules/con_rules scripts
against the POST-auto_fill state, to warm the cache for apply_recommendation_
rules/apply_constraint_rules. auto_fill's own internal helper
(_satisfied_recommendation) calls the exact same bml_eval.allowed_values_for_
script/condition_holds machinery against rec_rules, a few lines EARLIER,
with no prefetch covering it -- confirmed live to cost 20-21s of serial
Tier-2 round-trips on pass 0. This tests that a prefetch now fires before
auto_fill's own script evaluation, not just after it.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i)
            for i, v in enumerate(values, start=1)]


class _RecordingBmlEval:
    """Records call order so the test can assert prefetch happens before
    auto_fill's own serial script evaluation, not just after it."""

    def __init__(self):
        self.calls: list[tuple] = []

    def prefetch_tier2(self, requests):
        self.calls.append(("prefetch_tier2", list(requests)))

    def allowed_values_for_script(self, script, variables, cache_id=None):
        self.calls.append(("allowed_values_for_script", script, dict(variables)))
        return None

    def condition_holds(self, script, variables, cache_id=None):
        self.calls.append(("condition_holds", script, dict(variables)))
        return None

    def hide_for_script(self, script, variables, cache_id=None):
        self.calls.append(("hide_for_script", script, dict(variables)))
        return None


def test_prefetch_fires_before_auto_fills_own_script_evaluation():
    target = ConfigAttr(
        entity_id=2, variable_name="target_attr", display_label="Target",
        required=False, default_value="", select_type="single",
        options=_menu("YES", "NO"),
    )
    rec_rule = RecommendationRule(
        rule_name="r1", condition_attr_id=0, condition_value="",
        target_attr_id=2, script='return "YES";',
    )
    bml_eval = _RecordingBmlEval()
    eng = CpqEngine()

    eng.evaluate_rules_loop(
        [target], {}, {}, [], [rec_rule], [], bml_eval=bml_eval,
    )

    kinds = [c[0] for c in bml_eval.calls]
    assert "allowed_values_for_script" in kinds, (
        "test setup must actually exercise auto_fill's own script path"
    )
    first_direct_call = kinds.index("allowed_values_for_script")

    # Several prefetch_tier2 calls happen per pass (hiding, then this rule's
    # own, then rec/con again post-auto_fill) -- find the one that actually
    # covers this rule's script, not just the first prefetch_tier2 call ever
    # (e.g. the hiding-rules prefetch, empty here since hiding=[]).
    covering_prefetch_indices = [
        i for i, c in enumerate(bml_eval.calls)
        if c[0] == "prefetch_tier2"
        and any(req[0] == "values" and req[1] == 'return "YES";' for req in c[1])
    ]
    assert covering_prefetch_indices, (
        "no prefetch_tier2 call included this rule's script at all"
    )
    assert covering_prefetch_indices[0] < first_direct_call, (
        "a prefetch_tier2 call covering this rule's script must warm the "
        "cache before auto_fill's own _satisfied_recommendation calls the "
        "same script directly"
    )
