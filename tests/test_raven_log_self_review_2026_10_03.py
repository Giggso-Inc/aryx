"""Fixes from the PR #422 self-review: no raw exception text in records, never-raise, lock order, per-run counters."""
from __future__ import annotations

import re
import threading
from pathlib import Path

import aryx.raven_log as m
from aryx.cpq.auto_fill_stages import fill_log
from aryx.log_safe import ora_code

SRC = Path(__file__).resolve().parents[1] / "src" / "aryx"


def test_ora_code_returns_code_never_message():
    assert ora_code(Exception("bad value 'Jane' ORA-01722: invalid number")) == "ORA-01722"
    assert ora_code(Exception("DPY-4001 something")) == "DPY-4001"
    assert ora_code(Exception("no code here, secret=abc")) == ""


def test_no_record_context_carries_raw_exception_text():
    bad = re.compile(r'"error":\s*str\(exc\)\[:')
    hits = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if bad.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []


def test_raven_log_never_raises_when_scrub_or_run_id_fail(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "_scrub", boom)
    assert m.raven_log("INFO", "P4", "x", context={"a": 1}) == {}
    monkeypatch.undo()
    monkeypatch.setattr(m, "current_run_id", boom)
    assert m.raven_log("INFO", "P4", "x") == {}


def test_get_sinks_with_empty_config_cache_does_not_deadlock():
    m.reload_config()  # _CFG and _SINKS both empty
    done = []
    t = threading.Thread(target=lambda: done.append(m._get_sinks()), daemon=True)
    t.start()
    t.join(timeout=5)
    assert done, "_get_sinks deadlocked on the non-reentrant lock"


def test_rule_fire_counter_is_per_run(monkeypatch):
    run = {"id": "A"}
    monkeypatch.setattr(fill_log, "current_run_id", lambda: run["id"])
    assert fill_log.count_rule_fire() == 1
    assert fill_log.count_rule_fire() == 2
    run["id"] = "B"
    assert fill_log.count_rule_fire() == 1
    run["id"] = "A"  # an overlapping turn A must keep its own count
    assert fill_log.count_rule_fire() == 3


def test_static_fallback_dedupe_is_per_run(monkeypatch):
    run = {"id": "A"}
    monkeypatch.setattr(fill_log, "current_run_id", lambda: run["id"])
    assert fill_log.fallback_static_first_in_turn(("x", 1)) is True
    run["id"] = "B"
    assert fill_log.fallback_static_first_in_turn(("x", 1)) is True
    run["id"] = "A"
    assert fill_log.fallback_static_first_in_turn(("x", 1)) is False


def test_per_run_state_is_bounded():
    store: dict = {}
    for i in range(fill_log._RUNS_KEPT + 50):
        fill_log._per_run(store, f"r{i}", int)
    assert len(store) == fill_log._RUNS_KEPT
