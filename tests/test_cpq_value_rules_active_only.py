"""docs/CPQ_RULE_STATUS_AND_CONSTRAINT_DISPATCH_ROOT_CAUSE_AND_FIX_PLAN_2026-08-14.md
(Bug 1):

_load_value_rules previously called rdb.fetch_value_rules(...) WITHOUT
active_only=True -- unlike load_hiding_rules' fetch_rules(..., "11", ...)
call, which already opted into this filter for the exact same reason
(fetch_value_rules'/fetch_rules' own docstrings: BigMachines exports
routinely carry dead/superseded rules at status=3 alongside the live one).

Live-confirmed real harm: a DISABLED (status=3) recommendation rule
("Default hardware version for APX Next") was still being loaded and
applied, assigning a value the business had explicitly turned off.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine


def test_load_value_rules_passes_active_only_true(monkeypatch):
    eng = CpqEngine()
    calls = []

    def _fake_fetch_value_rules(workspace_id, catalog_prefix="", active_only=False):
        calls.append(active_only)
        return []

    fake_rdb = type("R", (), {
        "fetch_value_rules": staticmethod(_fake_fetch_value_rules),
        "fetch_function_scripts": staticmethod(lambda *a, **k: {}),
    })()

    def _fake_load_rule_join_data(workspace_id, catalog_prefix):
        return fake_rdb, {}, {}, {}, {}

    monkeypatch.setattr(eng, "_load_rule_join_data", _fake_load_rule_join_data)

    with patch("aryx.cpq.engine.IngestQuestionStore",
               side_effect=RuntimeError("no db in unit test")):
        eng._load_value_rules(workspace_id=21, catalog_prefix="ApxNextConfig")

    assert calls == [True], (
        "_load_value_rules must call fetch_value_rules with active_only=True "
        "-- otherwise a disabled (status=3) recommendation/constraint rule "
        "can still fire, e.g. a superseded default overriding the customer's "
        "real answer"
    )


def test_fetch_value_rules_emits_status_clause_only_when_active_only(monkeypatch):
    """fetch_value_rules must add the same status='1' SQL clause active_only
    already gets on fetch_rules() -- and must NOT add it when active_only is
    left at its default False, so existing (non-status-aware) callers stay
    byte-for-byte unaffected."""
    from aryx.cpq.rdb import PostgresCpqRdb

    class _FakeCursor:
        def __init__(self, capture):
            self._capture = capture

        def execute(self, query, params):
            self._capture["query"] = query

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def __init__(self, capture):
            self._capture = capture

        def cursor(self):
            return _FakeCursor(self._capture)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    rdb = PostgresCpqRdb.__new__(PostgresCpqRdb)

    capture_active = {}
    monkeypatch.setattr(rdb, "_connection", lambda: _FakeConn(capture_active))
    rdb.fetch_value_rules(1, active_only=True)
    assert "status" in capture_active["query"]

    capture_default = {}
    monkeypatch.setattr(rdb, "_connection", lambda: _FakeConn(capture_default))
    rdb.fetch_value_rules(1)
    assert "status" not in capture_default["query"]
