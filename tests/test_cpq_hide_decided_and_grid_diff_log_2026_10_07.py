"""Diagnostics only: a master-string hide rule that DECIDES is logged (a later "show" re-adds what an earlier rule hid),
and the grid-quantity step reports what it removed from / added to the pending list. Neither may change a result."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.api.ask_turn_steps import grid_diff_log
from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.hiding_rules import unknown_log
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from tests.test_cpq_hide_unknown_diagnostic_2026_10_07 import (  # noqa: PLC0415 -- shared fixtures
    BASE, PLAIN, SEQ_ROWS, WRITER_SCRIPT, _attrs, _flag, _rule)


@pytest.fixture(autouse=True)
def _fresh():
    unknown_log._SEEN.clear()
    yield
    unknown_log._SEEN.clear()


@pytest.fixture
def logged():
    out = []
    with patch.object(unknown_log, "would_log", return_value=True), \
            patch.object(unknown_log, "raven_log", side_effect=lambda *a, **k: out.append(k["context"])):
        yield out


def _decided(out):
    return [c for c in out if c["reason_code"].startswith("DECIDED_")]


def test_a_decided_master_string_rule_is_logged_with_its_outcome(logged):
    with _flag(True), patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=True):
        assert apply_hiding_rules(_attrs(), dict(BASE), [_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
                                  workspace_id=1)[2] == {"widgetAttr"}
    (line,) = _decided(logged)
    assert (line["selected_option"], line["reason_code"], line["attr"]) == ("hide", "DECIDED_BY_MASTER_STRING", "widgetAttr")


def test_a_show_is_logged_too_and_names_the_evaluator_when_the_master_string_did_not_decide(logged):
    with _flag(True), patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=None), \
            patch.object(BmlEvaluator, "hide_for_script", return_value=False):
        apply_hiding_rules(_attrs(), dict(BASE), [_rule()], bml_eval=BmlEvaluator({}, use_llm=False), workspace_id=1)
    (line,) = _decided(logged)
    assert (line["selected_option"], line["reason_code"]) == ("show", "DECIDED_BY_SCRIPT_EVALUATOR")


def test_a_rule_without_a_master_writer_is_not_logged(logged):
    with _flag(True), patch.object(BmlEvaluator, "hide_for_script", return_value=True):
        apply_hiding_rules(_attrs(), dict(BASE), [_rule(PLAIN, writers=False)],
                           bml_eval=BmlEvaluator({}, use_llm=False), workspace_id=1)
    assert _decided(logged) == []


def test_the_same_decision_is_logged_once_across_passes(logged):
    with _flag(True), patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=True):
        for _ in range(4):
            apply_hiding_rules(_attrs(), dict(BASE), [_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
                               workspace_id=1)
    assert len(_decided(logged)) == 1


def test_with_debug_off_nothing_is_logged_and_the_result_is_the_same():
    with patch.object(unknown_log, "would_log", return_value=False), patch.object(unknown_log, "raven_log") as rl, \
            _flag(True), patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=True):
        hidden = apply_hiding_rules(_attrs(), dict(BASE), [_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
                                    workspace_id=1)[2]
    assert hidden == {"widgetAttr"} and not rl.called


def test_a_failing_decision_log_never_breaks_hiding(logged):
    with patch.object(unknown_log, "raven_log", side_effect=RuntimeError("boom")), _flag(True), \
            patch("aryx.cpq.hiding_rules.apply.hide_with_master_string", return_value=True):
        assert apply_hiding_rules(_attrs(), dict(BASE), [_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
                                  workspace_id=1)[2] == {"widgetAttr"}


# --- grid-quantity step: removed / added names -----------------------------------------------------------------
def _attr(vn):
    return SimpleNamespace(variable_name=vn)


@pytest.fixture
def grid_logged():
    out = []
    with patch.object(grid_diff_log, "would_log", return_value=True), \
            patch.object(grid_diff_log, "raven_log", side_effect=lambda *a, **k: out.append(k["context"])):
        yield out


def test_the_grid_diff_names_what_was_removed_and_added(grid_logged):
    before = grid_diff_log.names_before([_attr("a"), _attr("selector"), _attr("b")])
    grid_diff_log.log_grid_diff(before, [_attr("a"), _attr("b"), _attr("qtyHolder1"), _attr("qtyHolder2")])
    (ctx,) = grid_logged
    assert (ctx["removed"], ctx["added"], ctx["added_count"], ctx["selected_option"]) == (
        ["selector"], ["qtyHolder1", "qtyHolder2"], 2, "changed")


def test_an_unchanged_pending_list_is_reported_unchanged(grid_logged):
    before = grid_diff_log.names_before([_attr("a")])
    grid_diff_log.log_grid_diff(before, [_attr("a")])
    assert grid_logged[0]["selected_option"] == "unchanged"


def test_the_grid_diff_list_is_capped(grid_logged):
    before = grid_diff_log.names_before([])
    grid_diff_log.log_grid_diff(before, [_attr(f"q{i}") for i in range(60)])
    assert len(grid_logged[0]["added"]) == 40 and grid_logged[0]["added_count"] == 60


def test_with_debug_off_nothing_is_copied_or_logged():
    with patch.object(grid_diff_log, "would_log", return_value=False), patch.object(grid_diff_log, "raven_log") as rl:
        assert grid_diff_log.names_before([_attr("a")]) is None
        grid_diff_log.log_grid_diff(None, [_attr("a")])
    rl.assert_not_called()
