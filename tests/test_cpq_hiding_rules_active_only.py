"""docs/config_consistency_issues_2026-07-30.md (Issue 5 follow-up):
load_hiding_rules() previously called rdb.fetch_rules(..., "11", ...) WITHOUT
active_only=True — unlike rule_type="6" flow rules, which already opted into
this filter for the exact same reason (fetch_rules' own docstring: BigMachines
exports routinely carry dead/superseded rules at status=3 alongside the live
one).

Live-confirmed real harm: a DISABLED (status=3) hiding rule ("Hide Frequency
Band & Extend Range if Product is selected as APX Enhanced") was still being
loaded and evaluated for an APX NEXT Enhanced order — its script condition
reads modelSelectionFrequencyBandMsl_astro's OWN just-set value and hides the
attribute right back, wiping the customer's Frequency Band answer on the same
turn it was recorded.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


def test_load_hiding_rules_passes_active_only_true(monkeypatch):
    eng = CpqEngine()
    calls = []

    def _fake_fetch_rules(workspace_id, rule_type, catalog_prefix="", active_only=False):
        calls.append((rule_type, active_only))
        return []

    fake_rdb = type("R", (), {
        "fetch_rules": staticmethod(_fake_fetch_rules),
        "fetch_function_scripts": staticmethod(lambda *a, **k: {}),
    })()

    def _fake_load_rule_join_data(workspace_id, catalog_prefix):
        return fake_rdb, {}, {}, {}, {}

    monkeypatch.setattr(eng, "_load_rule_join_data", _fake_load_rule_join_data)

    eng.load_hiding_rules(workspace_id=21, catalog_prefix="ApxNextConfig")

    assert ("11", True) in calls, (
        "load_hiding_rules must call fetch_rules with active_only=True — "
        "otherwise a disabled (status=3) hiding rule can still fire and "
        "silently hide/wipe a customer's just-recorded answer"
    )
