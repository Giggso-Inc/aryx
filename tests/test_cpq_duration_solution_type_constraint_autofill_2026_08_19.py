"""Live-confirmed root cause for the earlier "Duration has no active
default" finding: that conclusion only checked recommendation-typed rule
actions (action_type=1) for solutionTypeDuration_astro. Constraint-typed
actions (action_type=2) can ALSO deterministically resolve to a single
real value via a script-computed allowed-value list -- exactly the same
mechanism as Package Type's ICE-KIT rule (18131370895) traced earlier
this session. Rule 18654807040 ("Default Duration to 5 Years when Radio
Management (MSI Hosted) or 7 Years when RadioCentral with CPS is
selected"), active, does exactly this:

    retVal = "";
    if( ((solutionTypeDevices_astro=="RADIOCENTRAL PLUS CPS PROGRAMMING") OR (solutionTypeDevices_astro=="CLOUD RC"))){
            retVal = "7 YEARS";
    }
    elif((solutionTypeDevices_astro=="RADIO MANAGEMENT (MSI HOSTED)")){
            retVal = "5 YEARS";
    }
    return retVal;

Since Solution Type's own real catalog default_value is "RADIOCENTRAL
PLUS CPS PROGRAMMING" (confirmed live), this script resolves to exactly
one value, "7 YEARS" -- matching the native APX NEXT Enhanced screenshot
exactly. Tier 1's deterministic parser (evaluate_tier1) already handles
this plain if/elif-on-equality idiom natively (confirmed live -- no
stubbing needed, unlike Package Type's unsupported findinArray/split
idiom), so no code change was needed in engine.py for this attribute:
the existing "constraint narrows to exactly one legal value -> auto-fill,
no user decision needed" mechanism (the `len(valid_opts) == 1` branch)
already covers it once Solution Type is known. This test proves that
end-to-end, not just the script in isolation.
"""
from __future__ import annotations

from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption

_DURATION_SCRIPT = """
retVal = "";

if( ((solutionTypeDevices_astro=="RADIOCENTRAL PLUS CPS PROGRAMMING") OR (solutionTypeDevices_astro=="CLOUD RC"))){
        retVal = "7 YEARS";
}
elif((solutionTypeDevices_astro=="RADIO MANAGEMENT (MSI HOSTED)")){
        retVal = "5 YEARS";
}
return retVal;
"""


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_tier1_resolves_the_real_script_to_seven_years_for_radiocentral_cps():
    """Confirms Tier 1 handles this idiom natively -- no LLM/Tier-2
    stubbing required, unlike the Package Type ICE-KIT script."""
    from aryx.cpq.bml import evaluate_tier1
    result, blocked = evaluate_tier1(
        _DURATION_SCRIPT, {"solutionTypeDevices_astro": "RADIOCENTRAL PLUS CPS PROGRAMMING"},
    )
    assert result == ["7 YEARS"]
    assert blocked is False


def test_duration_auto_fills_to_seven_years_once_solution_type_known():
    """End-to-end: Solution Type already resolved to its own real default
    (RadioCentral + CPS Programming); Duration's real constraint rule
    must narrow it to exactly one legal value and auto-fill it via the
    engine's existing single-legal-value mechanism -- no code change,
    no allowlist entry, no asking."""
    duration_attr = ConfigAttr(
        entity_id=1, variable_name="solutionTypeDuration_astro",
        display_label="Duration", required=False, default_value="",
        select_type="single",
        options=_menu(
            "1 YEAR", "2 YEARS", "3 YEARS", "4 YEARS", "5 YEARS",
            "1 YEAR PROMO ONLY", "1 YEAR PROMO 1 YEAR PAID",
            "3 YEARS PAID 1 YEAR PROMO", "6 YEARS", "7 YEARS", "8 YEARS", "9 YEARS",
        ),
    )
    rule = ConstraintRule(
        rule_name="Default Duration to 5 Years when Radio Management (MSI Hosted) "
                   "or 7 Years when RadioCentral with CPS is selected",
        condition_attr_id=-1, condition_value="", target_attr_id=duration_attr.entity_id,
        allowed_values=[], script=_DURATION_SCRIPT,
    )

    eng = CpqEngine()
    bml_eval = BmlEvaluator({}, use_llm=False)
    filled_context = {"solutionTypeDevices_astro": "RADIOCENTRAL PLUS CPS PROGRAMMING"}

    constrained_opts = eng.apply_constraint_rules(
        [duration_attr], [rule], filled_context, bml_eval,
    )
    assert constrained_opts.get(duration_attr.entity_id) == ["7 YEARS"]

    filled, display_filled, pending = eng.auto_fill(
        [duration_attr], {}, constrained_opts=constrained_opts,
    )
    assert filled.get("solutionTypeDuration_astro") == "7 YEARS"
    assert display_filled.get("solutionTypeDuration_astro") == "7 YEARS"
    assert not any(a.variable_name == "solutionTypeDuration_astro" for a in pending)
