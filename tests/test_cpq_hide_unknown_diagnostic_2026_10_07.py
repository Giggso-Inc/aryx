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
WRITER_SCRIPT = (
    'cpqModel = modelVar;\n'
    'q = BMQL("SELECT distinct AttrName FROM $tblVar WHERE CPQModel=$cpqModel and BaseModel IN ($baseVar)");\n'
    'for r in q { out = out + r.AttrName + recSep; }\nreturn out;'
)
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
            script=WRITER_SCRIPT, conditions=[(2, "", "3")])]
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


# --- the exact step at which a master string could not be computed (written next to hide_unknown) ---------------
MULTI_COL_WRITER = 'q = BMQL("SELECT distinct AttrName,Seq,optionOrReqFlag FROM $tblVar WHERE CPQModel=$modelVar");'
SEQ_ROWS = [{"CPQModel": "M1", "BaseModel": "B1", "AttrName": "widgetAttr", "Seq": "1"}]


def _step_reasons(rule, filled, rows=SEQ_ROWS, attrs=None):
    out = []
    settings = MagicMock()
    settings.return_value.cpq_master_string_hide_enabled = True
    with patch("aryx.cpq.hiding_rules.master_writers.get_settings", settings), \
            patch("aryx.cpq.data_table.data_table_loader._load_all_tables", return_value=([], rows, [], [], [])), \
            patch.object(unknown_log, "would_log", return_value=True), \
            patch.object(unknown_log, "raven_log", side_effect=lambda *a, **k: out.append(k["context"]["reason_code"])):
        result = apply_hiding_rules(attrs or _attrs(), filled, [rule], bml_eval=BmlEvaluator({}, use_llm=False),
                                    workspace_id=1)[2]
    return out, result


def test_no_sequence_rows_for_the_scope_is_named():
    reasons, hidden = _step_reasons(_rule(), {**BASE, "countryVar": "ZZ"}, rows=[])
    assert reasons == ["NO_SEQUENCE_ROWS_FOR_SCOPE", "MASTER_STRING_UNRESOLVED"] and hidden == set()


def test_an_unsupported_writer_query_shape_is_named():
    rule = _rule()
    rule.master_writers[0].script = MULTI_COL_WRITER
    reasons, hidden = _step_reasons(rule, {**BASE, "countryVar": "ZZ"})
    assert reasons == ["WRITER_QUERY_SHAPE_UNSUPPORTED", "MASTER_STRING_UNRESOLVED"] and hidden == set()


def test_an_unknown_separator_is_named():
    attrs = [a for a in _attrs() if a.variable_name != "recSep"]
    reasons, hidden = _step_reasons(_rule(), {**BASE, "countryVar": "ZZ"}, attrs=attrs)
    assert reasons == ["SEPARATOR_UNKNOWN", "MASTER_STRING_UNRESOLVED"] and hidden == set()


def test_a_resolvable_master_string_logs_no_step_reason():
    reasons, hidden = _step_reasons(_rule(), {**BASE, "countryVar": "ZZ"})
    assert reasons == [] and hidden == set()                       # computed, attribute present -> shown


def test_a_writer_query_that_does_not_parse_is_named():
    rule = _rule()
    rule.master_writers[0].script = 'return "static";'
    reasons, hidden = _step_reasons(rule, {**BASE, "countryVar": "ZZ"})
    assert reasons == ["WRITER_QUERY_NOT_PARSED", "MASTER_STRING_UNRESOLVED"] and hidden == set()


def test_an_undecidable_writer_condition_is_logged_with_its_own_condition():
    rule = _rule()
    rule.master_writers[0].conditions = [(2, "x", "9")]            # an operator the declarative evaluator cannot decide
    seen = []
    settings = MagicMock()
    settings.return_value.cpq_master_string_hide_enabled = True
    with patch("aryx.cpq.hiding_rules.master_writers.get_settings", settings), \
            patch("aryx.cpq.data_table.data_table_loader._load_all_tables", return_value=([], SEQ_ROWS, [], [], [])), \
            patch.object(unknown_log, "would_log", return_value=True), \
            patch.object(unknown_log, "raven_log", side_effect=lambda *a, **k: seen.append(k["context"])), \
            patch("aryx.cpq.hiding_rules.master_string.writer_fires", return_value=None):
        apply_hiding_rules(_attrs(), dict(BASE), [rule], bml_eval=BmlEvaluator({}, use_llm=False), workspace_id=1)
    step = [c for c in seen if c["reason_code"] == "WRITER_CONDITION_UNKNOWN"][0]
    assert step["writers"][0]["writer"] == "w" and step["writers"][0]["conditions"] == [[2, "x", "9"]]
