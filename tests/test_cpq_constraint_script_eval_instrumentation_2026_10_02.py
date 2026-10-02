"""Phase 1 instrumentation (docs/CPQ_SEQUENTIAL_LLM_CONSTRAINT_EVAL_
IMPLEMENTATION_PLAN_2026-09-24.md): aggregate timing/counts around the
script-governed branches of apply_constraint_rules() -- allowed_values_
for_script() / condition_holds(), the two calls that can reach
BmlEvaluator's Tier-2 LLM path and the confirmed source of the 130s-1237s
per-rule gaps behind the CPQ turn-latency incident.

Pure observability: asserts the new "cpq_perf: constraint script-eval"
log line appears (with correct counts) when script-governed rules run,
and stays silent when none do -- no assertion on apply_constraint_rules'
own return value, which is untouched by this change.
"""
from __future__ import annotations

import logging

from aryx.cpq.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


def setup_function(_fn):
    clear_shared_bml_cache()


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _target_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="wirelessCarrier_astro",
        display_label="Wireless Carrier", required=False, default_value="",
        select_type="single", options=_menu("VERIZON", "ATT/FIRSTNET"),
    )


def _script_rule() -> ConstraintRule:
    return ConstraintRule(
        rule_name="Restrict Carrier for Region",
        condition_attr_id=0, condition_value="", target_attr_id=1,
        allowed_values=[], script='return "VERIZON";',
    )


def test_logs_aggregate_timing_when_script_rules_run(caplog):
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})

    with caplog.at_level(logging.INFO, logger="aryx.cpq.engine"):
        eng.apply_constraint_rules([attr], [_script_rule()], {}, bml_eval=bml_eval)

    matches = [r for r in caplog.records if "cpq_perf: constraint script-eval" in r.message]
    assert len(matches) == 1
    msg = matches[0].message
    assert "script_rules=1" in msg
    assert "condition_script_rules=0" in msg
    assert "total_script_eval_s=" in msg


def test_silent_when_no_script_governed_rules_run(caplog):
    """A pass with zero script-governed rules (e.g. all-declarative
    catalogs, or bml_eval=None) must not add log noise -- confirms the
    gate on _script_rule_count/_cond_script_rule_count, not just that
    SOME log line appears."""
    attr = _target_attr()
    eng = CpqEngine()

    with caplog.at_level(logging.INFO, logger="aryx.cpq.engine"):
        eng.apply_constraint_rules([attr], [], {}, bml_eval=None)

    matches = [r for r in caplog.records if "cpq_perf: constraint script-eval" in r.message]
    assert not matches


def test_instrumentation_does_not_raise_and_returns_a_dict():
    """Pure observability -- apply_constraint_rules must keep returning
    its normal dict shape unaffected by the new counters/timers. The
    actual constraint-narrowing semantics for script-backed rules are
    already covered by
    tests/test_cpq_constraint_narrows_via_script_backed_recommendation_2026_08_25.py
    and friends; this test only guards that Phase 1's instrumentation
    doesn't change the call contract."""
    attr = _target_attr()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})

    result = eng.apply_constraint_rules([attr], [_script_rule()], {}, bml_eval=bml_eval)

    assert isinstance(result, dict)
