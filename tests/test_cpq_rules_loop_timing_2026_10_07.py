"""Timing for the slow rules-loop turns (ws 1267: 5-10 minute turns, passes of 20-90 s). Diagnostic only: results are
unchanged, the stages that were unmeasured now log, and one line per turn says which stage took the time."""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from aryx.cpq.rules_loop import rules_loop
from aryx.cpq.rules_loop.rules_loop_state import LoopState
from aryx.cpq.rules_loop.rules_loop_timing import add_stage, stage_done, totals_line
from aryx.cpq.state import ConfigAttr, HidingRule


def _state() -> LoopState:
    return LoopState(attrs=[], filled={}, display_filled={}, sources={}, multi={}, dropped={})


def test_add_stage_accumulates_without_logging(caplog):
    state = _state()
    with caplog.at_level(logging.INFO):
        add_stage(state, "auto_fill", time.monotonic() - 2.0)
        add_stage(state, "auto_fill", time.monotonic() - 1.0)
    assert 2.9 < state.stage_s["auto_fill"] < 3.5
    assert not [r for r in caplog.records if "cpq_perf" in r.getMessage()]


def test_stage_done_accumulates_and_logs_in_the_cpq_perf_form(caplog):
    state = _state()
    with caplog.at_level(logging.INFO):
        stage_done(state, "apply_hiding_rules", time.monotonic() - 1.5, 3, "rules=2404 hidden=323")
    assert state.stage_s["apply_hiding_rules"] >= 1.5
    line = next(r.getMessage() for r in caplog.records if "apply_hiding_rules" in r.getMessage())
    assert line.startswith("cpq_perf: apply_hiding_rules took 1.5") and "pass=3 rules=2404 hidden=323" in line


def test_totals_line_lists_the_biggest_stage_first():
    state = _state()
    state.stage_s.update({"auto_fill": 4.0, "apply_hiding_rules": 61.2, "apply_constraint_rules": 0.3})
    line = totals_line(state, 70.0, 5)
    assert line.startswith("cpq_perf: rules_loop stage totals passes=5 total=70.0s ")
    assert line.index("apply_hiding_rules=61.2s") < line.index("auto_fill=4.0s") < line.index("apply_constraint_rules=0.3s")


def test_the_loop_emits_one_totals_line_per_turn(caplog):
    engine = MagicMock()
    engine.rank_rules_by_specificity.return_value = ([], [], [])

    def early(_engine, _pass, state, _scope):
        add_stage(state, "apply_hiding_rules", time.monotonic() - 2.0)

    with patch.object(rules_loop, "run_early_pass", early), patch.object(rules_loop, "run_late_pass", lambda *a: True), \
            caplog.at_level(logging.INFO):
        rules_loop.evaluate_rules_loop(engine, [], {}, {}, [], [], [])
    totals = [r.getMessage() for r in caplog.records if "rules_loop stage totals" in r.getMessage()]
    assert len(totals) == 1 and "passes=1" in totals[0] and "apply_hiding_rules=2." in totals[0]


def _attr(eid: int, vn: str) -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
                      options=[], source_id=eid)


def test_apply_hiding_rules_logs_how_many_script_rules_decided_and_how_long(caplog):
    attrs = [_attr(1, "a"), _attr(2, "b"), _attr(3, "c")]
    rules = [HidingRule(rule_name=f"r{i}", condition_attr_id=0, condition_value="", target_attr_id=i, script="x")
             for i in (1, 2, 3)]
    with patch.object(BmlEvaluator, "hide_for_script", side_effect=[True, False, None]), caplog.at_level(logging.INFO):
        _vis, _msgs, hidden = apply_hiding_rules(attrs, {}, rules, bml_eval=BmlEvaluator({}, use_llm=False))
    assert hidden == {"a"}                                                  # behaviour unchanged
    line = next(r.getMessage() for r in caplog.records if "cpq_perf: apply_hiding_rules" in r.getMessage())
    assert "rules=3 script_hide=1 script_show=1 script_unknown=1" in line and "script_s=" in line


def test_apply_hiding_rules_with_no_evaluator_counts_every_script_rule_unknown(caplog):
    attrs = [_attr(1, "a")]
    rules = [HidingRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=1, script="x")]
    with caplog.at_level(logging.INFO):
        apply_hiding_rules(attrs, {}, rules, bml_eval=None)
    line = next(r.getMessage() for r in caplog.records if "cpq_perf: apply_hiding_rules" in r.getMessage())
    assert "script_unknown=1" in line
