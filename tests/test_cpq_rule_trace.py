"""Tests for aryx.cpq.rule_trace (docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md,
Tier 1). RuleTraceStore is mocked -- no real DB -- local .jsonl writes go to
a tmp_path directory.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq import rule_trace
from aryx.cpq.logging_context import set_run_id


@pytest.fixture(autouse=True)
def _reset_module_state(tmp_path, monkeypatch):
    """Every test gets a clean _open_sessions dict, a tmp trace dir, and a
    mocked durable store -- module-level state must not leak between tests."""
    rule_trace._open_sessions.clear()
    set_run_id("")
    rule_trace._ctx_var.set(None)
    rule_trace._pass_var.set(0)

    settings = MagicMock()
    settings.cpq_rule_trace_dir = str(tmp_path)
    settings.cpq_rule_trace_orphan_timeout_hours = 24
    monkeypatch.setattr("aryx.config.get_settings", lambda: settings)

    mock_store = MagicMock()
    monkeypatch.setattr(rule_trace, "_store", lambda: mock_store)
    yield mock_store
    rule_trace._open_sessions.clear()
    set_run_id("")
    rule_trace._ctx_var.set(None)
    rule_trace._pass_var.set(0)


def _read_jsonl(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestRecordFire:
    def test_records_single_fired_rule(self, tmp_path, _reset_module_state):
        set_run_id("run-1")
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.bind_pass(0)
        rule_trace.record_fire(
            rule_type="hiding", rule_id="H1", attr="foo_vn", outcome="hide",
        )
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        entries = _read_jsonl(files[0])
        assert len(entries) == 1
        assert entries[0]["pass_num"] == 0
        assert entries[0]["rule_type"] == "hiding"
        assert entries[0]["rule_id"] == "H1"
        assert entries[0]["outcome"] == "hide"

    def test_noop_when_no_run_id_bound(self, tmp_path):
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="v", outcome="hide")
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_noop_when_context_never_bound(self, tmp_path):
        set_run_id("run-2")
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="v", outcome="hide")
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_appends_across_multiple_calls_same_run_id_in_order(self, tmp_path):
        set_run_id("run-3")
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.bind_pass(0)
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="a", outcome="hide")
        rule_trace.bind_pass(1)
        rule_trace.record_fire(rule_type="constraint", rule_id="C1", attr="b", outcome="allowed=[X]")
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1  # same session -> same file, not one per call
        entries = _read_jsonl(files[0])
        assert [e["seq_no"] for e in entries] == [1, 2]
        assert [e["pass_num"] for e in entries] == [0, 1]

    def test_durable_store_receives_same_entry(self, tmp_path, _reset_module_state):
        set_run_id("run-4")
        rule_trace.bind_context(7, "Sl3500e")
        rule_trace.bind_pass(2)
        rule_trace.record_fire(
            rule_type="recommendation", rule_id="RR1", attr="x", outcome="set=Y",
            bml_tier="script",
        )
        _reset_module_state.append_entry.assert_called_once()
        args = _reset_module_state.append_entry.call_args[0]
        assert args[0] == "run-4"  # run_id
        assert args[2] == 2        # pass_num
        assert args[3] == "recommendation"
        assert args[4] == "RR1"


class TestSealing:
    def test_new_session_after_seal_opens_new_file(self, tmp_path):
        set_run_id("run-5")
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="a", outcome="hide")
        rule_trace.seal("run-5")
        assert len(list(tmp_path.glob("*.jsonl"))) == 1

        set_run_id("run-6")
        rule_trace.record_fire(rule_type="hiding", rule_id="H2", attr="b", outcome="hide")
        files = sorted(tmp_path.glob("*.jsonl"))
        assert len(files) == 2  # new session -> new file, not appended to sealed one

    def test_record_fire_after_seal_is_noop(self, tmp_path):
        set_run_id("run-7")
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="a", outcome="hide")
        rule_trace.seal("run-7")
        before = _read_jsonl(next(tmp_path.glob("*.jsonl")))
        rule_trace.record_fire(rule_type="hiding", rule_id="H2", attr="b", outcome="hide")
        after = _read_jsonl(next(tmp_path.glob("*.jsonl")))
        assert before == after  # sealed session never accepts another write

    def test_seal_calls_durable_seal_with_status(self, tmp_path, _reset_module_state):
        set_run_id("run-8")
        rule_trace.bind_context(1, "ApxNextConfig")
        rule_trace.record_fire(rule_type="hiding", rule_id="H1", attr="a", outcome="hide")
        rule_trace.seal("run-8", status="post_approval")
        _reset_module_state.seal_session.assert_called_once_with("run-8", status="post_approval")

    def test_seal_with_no_open_trace_is_noop(self, tmp_path, _reset_module_state):
        rule_trace.seal("never-opened")
        _reset_module_state.seal_session.assert_not_called()


class TestOrphanSweep:
    def test_sweep_orphans_delegates_to_store_with_configured_timeout(self, _reset_module_state):
        _reset_module_state.sweep_orphans.return_value = ["run-x"]
        result = rule_trace.sweep_orphans()
        _reset_module_state.sweep_orphans.assert_called_once_with(timeout_hours=24)
        assert result == ["run-x"]

    def test_sweep_orphans_accepts_explicit_override(self, _reset_module_state):
        rule_trace.sweep_orphans(timeout_hours=1)
        _reset_module_state.sweep_orphans.assert_called_once_with(timeout_hours=1)
