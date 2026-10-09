"""The rule-consistency check logs how long each of its passes took.

Live turns spent 25-38 minutes in the step-2 rule-consistency check with
nothing logged inside it; ask.rule_consistency.timing names the slow pass.
"""

from __future__ import annotations

from types import SimpleNamespace

from aryx.cpq.recommendation_and_constraint_rules import inconsistencies as inc


def test_timing_record_names_each_pass(monkeypatch):
    records = []
    monkeypatch.setattr(inc, "raven_log", lambda level, crit, msg, **kw: records.append((level, msg, kw)))
    engine = SimpleNamespace(
        apply_hiding_rules=lambda *a, **k: ([], [], set()),
        apply_constraint_rules=lambda *a, **k: {},
    )
    issues = inc.find_rule_inconsistencies(engine, {"a": "1"}, [], [], [], [], workspace_id=1)
    assert issues == []
    level, msg, kw = next(r for r in records if r[1].startswith("ask.rule_consistency.timing"))
    ctx = kw["context"]
    assert level == "INFO"
    for key in ("duration_ms", "hiding_ms", "constraint_ms", "recommendation_ms",
                "constraint_rule_count", "hiding_rule_count", "issue_count"):
        assert key in ctx
