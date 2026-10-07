"""A script hide rule that gives no answer leaves its target visible; it now says why, once per (run, rule, target,
reason), only when DEBUG is on, and the diagnostic can never change or break rule evaluation."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.hiding_rules import unknown_log
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from aryx.cpq.state import ConfigAttr, HidingRule, RecommendationRule

HIDE_D = (
    'arr = SPLIT(masterVar,recSep);\n'
    'idx = findinarray(arr,"widgetAttr");\n'
    'if(idx ==-1){ return TRUE; } else { if(baseVar==""){ return TRUE; } }\n'
    'return FALSE;'
)
PLAIN = 'return someVar == "x";'
BASE = {"modelVar": "M1", "baseVar": "B1"}


def _attr(eid: int, vn: str, default: str = "") -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False,
                      default_value=default, options=[], source_id=eid)


def _attrs() -> list[ConfigAttr]:
    return [_attr(1, "widgetAttr"), _attr(2, "countryVar"), _attr(3, "masterVar"), _attr(4, "baseVar"),
            _attr(5, "recSep", "@@@"), _attr(6, "modelVar"), _attr(7, "tblVar", "seqTable")]


def _rule(script: str = HIDE_D, writers: bool = True) -> HidingRule:
    rule = HidingRule(rule_name="h", condition_attr_id=0, condition_value="", target_attr_id=1, script=script)
    if writers:
        rule.master_writers = [RecommendationRule(
            rule_name="w", condition_attr_id=2, condition_value="", target_attr_id=3,
            script="q = BMQL(\"SELECT distinct AttrName FROM $tblVar\");", conditions=[(2, "", "3")])]
    return rule


@contextmanager
def _flag(on: bool):
    settings = MagicMock()
    settings.return_value.cpq_master_string_hide_enabled = on
    with patch("aryx.cpq.hiding_rules.master_writers.get_settings", settings), \
            patch("aryx.cpq.data_table.data_table_loader._load_all_tables", return_value=([], [], [], [], [])):
        yield


@pytest.fixture(autouse=True)
def _fresh():
    unknown_log._SEEN.clear()
    yield
    unknown_log._SEEN.clear()


@pytest.fixture
def logged():
    with patch.object(unknown_log, "would_log", return_value=True), patch.object(unknown_log, "raven_log") as rl:
        yield rl


def _apply(rule, evaluator="default", filled=None):
    bml = BmlEvaluator({}, use_llm=False) if evaluator == "default" else evaluator
    return apply_hiding_rules(_attrs(), dict(filled or BASE), [rule], bml_eval=bml, workspace_id=1)[2]


def _reasons(rl):
    return [c.kwargs["context"]["reason_code"] for c in rl.call_args_list]


def test_flag_off_with_a_writer_rule_logs_the_flag_as_the_reason(logged):
    with _flag(False):
        assert _apply(_rule()) == set()                              # behaviour unchanged: left visible
    assert _reasons(logged) == ["MASTER_STRING_FLAG_OFF"]
    ctx = logged.call_args.kwargs["context"]
    assert (ctx["rule_name"], ctx["attr"], ctx["selected_option"]) == ("h", "widgetAttr", "left_visible")


def test_a_master_string_that_could_not_be_computed_is_named(logged):
    with _flag(True), patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=None), \
            patch.object(BmlEvaluator, "hide_for_script", return_value=None):
        assert _apply(_rule()) == set()
    assert _reasons(logged) == ["MASTER_STRING_UNRESOLVED"]


def test_a_master_search_without_a_writer_rule_is_named(logged):
    with _flag(True), patch.object(BmlEvaluator, "hide_for_script", return_value=None):
        assert _apply(_rule(writers=False)) == set()
    assert _reasons(logged) == ["MASTER_SEARCH_WITHOUT_WRITER_RULE"]


def test_no_evaluator_is_named(logged):
    with _flag(True):
        assert _apply(_rule(), evaluator=None) == set()
    assert _reasons(logged) == ["NO_EVALUATOR"]


def test_an_evaluator_that_does_not_know_is_named(logged):
    with _flag(True), patch.object(BmlEvaluator, "hide_for_script", return_value=None):
        assert _apply(_rule(PLAIN, writers=False)) == set()
    assert _reasons(logged) == ["EVALUATOR_UNKNOWN"]


def test_a_decided_rule_logs_nothing(logged):
    with _flag(True), patch.object(BmlEvaluator, "hide_for_script", return_value=True):
        assert _apply(_rule(PLAIN, writers=False)) == {"widgetAttr"}
    logged.assert_not_called()


def test_the_same_undecided_rule_is_logged_once_across_passes(logged):
    with _flag(False):
        for _ in range(5):
            _apply(_rule())
    assert len(logged.call_args_list) == 1


def test_with_debug_off_nothing_is_computed_or_logged():
    with patch.object(unknown_log, "would_log", return_value=False), patch.object(unknown_log, "raven_log") as rl, \
            patch.object(unknown_log, "unknown_reason") as reason, _flag(False):
        _apply(_rule())
    rl.assert_not_called()
    reason.assert_not_called()


def test_a_failing_diagnostic_never_breaks_hiding(logged):
    logged.side_effect = RuntimeError("boom")
    with _flag(False):
        assert _apply(_rule()) == set()                              # no exception, same result


def test_an_unexpected_rule_object_never_breaks_hiding():
    with patch.object(unknown_log, "would_log", return_value=True):
        unknown_log.log_unknown_script_hide(object(), "x", True)    # no rule_name: swallowed


def test_concurrent_logging_of_the_same_rule_writes_one_line(logged):
    import threading
    rule = _rule()
    threads = [threading.Thread(target=unknown_log.log_unknown_script_hide, args=(rule, "widgetAttr", True))
               for _ in range(20)]
    with _flag(False):
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(logged.call_args_list) == 1
