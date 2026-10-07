"""A script hide rule that gives no answer leaves its target visible; it now says why, once per (run, rule, target,
reason), and the hide/show behaviour itself is unchanged."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.hiding_rules import unknown_log
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from tests.test_cpq_master_string_hide_2026_10_05 import BASE, _attrs, _flag, _hide_rule


@pytest.fixture(autouse=True)
def _fresh():
    unknown_log._SEEN.clear()
    yield
    unknown_log._SEEN.clear()


@pytest.fixture
def logged():
    with patch.object(unknown_log, "would_log", return_value=True), \
            patch.object(unknown_log, "raven_log") as rl:
        yield rl


def _apply(rule, evaluator="default", filled=None):
    bml = BmlEvaluator({}, use_llm=False) if evaluator == "default" else evaluator
    return apply_hiding_rules(_attrs(), dict(filled or BASE), [rule], bml_eval=bml, workspace_id=1)[2]


def _reasons(rl):
    return [c.kwargs["context"]["reason_code"] for c in rl.call_args_list]


def test_flag_off_with_writer_rule_logs_the_flag_as_the_reason(logged):
    with _flag(False):
        assert _apply(_hide_rule()) == set()                       # behaviour unchanged: left visible
    assert _reasons(logged) == ["MASTER_STRING_FLAG_OFF"]
    ctx = logged.call_args.kwargs["context"]
    assert (ctx["rule_name"], ctx["attr"], ctx["selected_option"]) == ("h", "widgetAttr", "left_visible")


def test_master_search_without_a_writer_rule_is_named(logged):
    with _flag(True):
        assert _apply(_hide_rule(with_writers=False)) == set()
    assert _reasons(logged) == ["MASTER_SEARCH_WITHOUT_WRITER_RULE"]


def test_no_evaluator_is_named(logged):
    with _flag(True):
        assert _apply(_hide_rule(), evaluator=None) == set()
    assert _reasons(logged) == ["NO_EVALUATOR"]


def test_a_decided_rule_logs_nothing(logged):
    with _flag(True):
        assert _apply(_hide_rule(), filled={"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}) == {"widgetAttr"}
    logged.assert_not_called()


def test_the_same_undecided_rule_is_logged_once_across_passes(logged):
    with _flag(False):
        for _ in range(5):
            _apply(_hide_rule())
    assert len(logged.call_args_list) == 1


def test_nothing_is_logged_when_debug_is_off():
    with patch.object(unknown_log, "would_log", return_value=False), patch.object(unknown_log, "raven_log") as rl, \
            _flag(False):
        _apply(_hide_rule())
    rl.assert_not_called()
