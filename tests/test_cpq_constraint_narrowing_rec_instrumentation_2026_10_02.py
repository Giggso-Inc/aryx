"""Phase 1b instrumentation (docs/CPQ_SEQUENTIAL_LLM_CONSTRAINT_EVAL_
IMPLEMENTATION_PLAN_2026-09-24.md): aggregate timing/counts around the
script-backed narrowing_rec_rules branch of apply_constraint_rules() --
same allowed_values_for_script() Tier-2 path Phase 1 already instrumented
for real ConstraintRules, but this loop (script-backed RecommendationRule
narrowing, see test_cpq_constraint_narrows_via_script_backed_recommendation_
2026_08_25.py) had none of its own.

Live-confirmed (WS110, 2026-09-25): apply_constraint_rules took 98.661s in
one evaluate_rules_loop pass while the existing "constraint script-eval"
summary line for that same call showed total_script_eval_s=1.807s -- ~97s
unaccounted for, with this loop the only other Tier-2 call site in the
method and (per the sibling 2026-08-25 regression note) the confirmed
source of comparable-magnitude cost before its own "skip if already
filled" guard was added.

Pure observability: asserts the new "cpq_perf: constraint narrowing-rec
script-eval" log line appears (with correct count) when script-backed
narrowing rules actually run, and stays silent otherwise -- no assertion
on apply_constraint_rules' own return value, which is untouched by this
change.
"""
from __future__ import annotations

import logging

from aryx.cpq.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule

_MOUNT_NARROWING_SCRIPT = (
    'if(modelSelectionSelectModel_viSoln=="SVX VIDEO REMOTE SPEAKER MIC UL"){\n'
    'retVal ="Shirt Magnetic Mount"|"Jacket Magnetic Mount"|"Shirt Clip Mount"'
    '|"Jacket Clip Mount"|"Locking Molle Mount"|"TEK-LOK Belt Mount";\n'
    '}\n'
    'else\n{\n'
    'retVal ="Shirt Magnetic Mount"|"Jacket Magnetic Mount"|"Shirt Clip Mount"'
    '|"Jacket Clip Mount"|"Locking Molle Mount";\n'
    '}'
)


def setup_function(_fn):
    clear_shared_bml_cache()


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _mounting_type_array() -> ConfigAttr:
    return ConfigAttr(
        entity_id=70284, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
            "Jacket Clip Mount", "Locking Molle Mount", "Magnetic Mount",
        ),
    )


def _narrowing_rule() -> RecommendationRule:
    return RecommendationRule(
        rule_name="Default Values for VX650 Mounting Type Array",
        condition_attr_id=0, condition_value="", target_attr_id=70284,
        script=_MOUNT_NARROWING_SCRIPT,
    )


def test_logs_aggregate_timing_when_narrowing_rec_rules_run(caplog):
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic"}

    with caplog.at_level(logging.INFO, logger="aryx.cpq.engine"):
        eng.apply_constraint_rules(
            [attr], [], filled, bml_eval=bml_eval,
            narrowing_rec_rules=[_narrowing_rule()],
        )

    matches = [
        r for r in caplog.records
        if "cpq_perf: constraint narrowing-rec script-eval" in r.message
    ]
    assert len(matches) == 1
    msg = matches[0].message
    assert "script_rules=1" in msg
    assert "script_eval_s=" in msg


def test_silent_when_no_narrowing_rec_rules_run(caplog):
    """No narrowing_rec_rules, and a pass where the target is already
    filled (script never actually evaluated) must both stay silent --
    confirms the gate on _narrow_rule_count, not just that SOME log line
    appears somewhere."""
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})

    with caplog.at_level(logging.INFO, logger="aryx.cpq.engine"):
        eng.apply_constraint_rules([attr], [], {}, bml_eval=bml_eval)

    matches = [
        r for r in caplog.records
        if "cpq_perf: constraint narrowing-rec script-eval" in r.message
    ]
    assert not matches

    caplog.clear()
    already_filled = {
        "modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic",
        "mountingTypeArray_viSoln": "Shirt Magnetic Mount",
    }
    with caplog.at_level(logging.INFO, logger="aryx.cpq.engine"):
        eng.apply_constraint_rules(
            [attr], [], already_filled, bml_eval=bml_eval,
            narrowing_rec_rules=[_narrowing_rule()],
        )

    matches = [
        r for r in caplog.records
        if "cpq_perf: constraint narrowing-rec script-eval" in r.message
    ]
    assert not matches


def test_instrumentation_does_not_raise_and_returns_a_dict():
    """Pure observability -- apply_constraint_rules must keep returning
    its normal dict shape unaffected by the new counters/timers. Actual
    narrowing semantics are already covered by
    test_cpq_constraint_narrows_via_script_backed_recommendation_2026_08_25.py;
    this test only guards that Phase 1b's instrumentation doesn't change
    the call contract."""
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic"}

    result = eng.apply_constraint_rules(
        [attr], [], filled, bml_eval=bml_eval,
        narrowing_rec_rules=[_narrowing_rule()],
    )

    assert isinstance(result, dict)
