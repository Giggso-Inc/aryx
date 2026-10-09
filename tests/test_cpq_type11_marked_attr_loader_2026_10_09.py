"""Loader-level pin for the `_rule_key`/`marked` fix (rule_targets.py) --
review-requested (2026-10-09) because the four `_rule_key`-only tests in
test_cpq_rule_key_marked_attr_resolution_2026_10_09.py never exercise
`_load_type11_hiding_rules`, so "rule now hides FCC for APX 1500 Enhanced"
was unverified.

This pins the two outcomes that actually follow from the fix for a
no-input/no-action, marked-attr-only, declarative rule (the live shape of
ws 1267 rule 5030760 "Hide do you required Radio FED FCC"), across both
states of `cpq_empty_condition_rule_true_enabled` (plan F10):

- F10 OFF (the real ws 1267 dev default, confirmed live 2026-10-09): the
  rule now resolves a target via `marked`, but `_load_type11_hiding_rules`
  still treats its empty input list as "unresolved" and drops it -- same
  outcome as before this fix landed. The fix alone changes nothing for this
  rule while F10 stays off.
- F10 ON: the rule is now kept, as an unconditional (`always=True`) hide --
  NOT a "hide for non-Federal customers" (the real rule, confirmed live, has
  no condition at all: 0 inputs, 0 actions, status=1, ref_id scoped to the
  aPXNext BmCatalog node). `cpq_rule_scope_filter_enabled` is a separate,
  independent concern: it filters by `ref_id` membership in the resolved
  model's `scope_node_ids`, which this loader never populates (scope is
  attached later by `rule_scope.tag_ref_ids`/`scope_rules_by_ancestry`), so
  it is out of scope for this loader-level test.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.hiding_rules.type11 import _load_type11_hiding_rules

_RULE_NAME = "Hide do you required Radio FED FCC"


def _fake_rdb_marked_attr_only(entity_id: int, source_id: int, target_attr_id: int):
    """A minimal rdb double: one declarative hiding rule (rule_type=11, no
    script) with zero BmConfigRuleInput/Action rows -- its only target
    linkage is a BmConfigMarkedAttr row keyed under `source_id`, matching
    rule 5030760's real shape exactly. The row always carries a 5th (ref_id)
    element -- this test environment's own default settings resolve
    `cpq_rule_scope_filter_enabled` to True, so `_load_type11_hiding_rules`
    always requests `with_ref_id=True` and reads `row[4]` regardless of what
    this test is pinning down."""

    def _fetch_rules(workspace_id, rule_type, catalog_prefix="", active_only=False, **_kw):
        assert rule_type == "11"
        return [(entity_id, source_id, _RULE_NAME, -1, "")]  # fn_id=-1: declarative, not script

    return type("R", (), {
        "fetch_rules": staticmethod(_fetch_rules),
        "fetch_function_scripts": staticmethod(lambda *a, **k: {}),
    })()


def _load_rules_for(monkeypatch, eng, entity_id: int, source_id: int, target_attr_id: int):
    """Calls `_load_type11_hiding_rules` directly -- NOT `eng.load_hiding_
    rules` -- so this test pins only the `_rule_key`/F10 interaction this
    PR touches. `load_hiding_rules` additionally runs
    `rule_scope.scope_rules_by_ancestry` and merges in `_load_value_rules`'
    value-less hiding rules; both are separate, already-existing concerns
    this test deliberately does not exercise."""
    fake_rdb = _fake_rdb_marked_attr_only(entity_id, source_id, target_attr_id)

    def _fake_load_rule_join_data(workspace_id, catalog_prefix):
        inputs: dict = {}
        actions: dict = {}
        marked = {source_id: [target_attr_id]}  # keyed under source_id, not entity_id -- the real shape
        chain: dict = {}
        return fake_rdb, inputs, actions, marked, chain

    monkeypatch.setattr(eng, "_load_rule_join_data", _fake_load_rule_join_data)
    return _load_type11_hiding_rules(eng, 1267, "", 0.0, "")


def test_marked_attr_only_rule_still_dropped_with_f10_off(monkeypatch):
    """The real ws 1267 dev state (confirmed live 2026-10-09): F10 defaults
    off, so even though the target now resolves, the rule's empty input list
    still makes it 'unresolved' and it is still dropped -- this fix alone
    does not change behavior while F10 stays off."""
    eng = CpqEngine()
    with patch(
        "aryx.cpq.hiding_rules.type11.get_settings",
    ) as mock_settings:
        mock_settings.return_value.cpq_empty_condition_rule_true_enabled = False
        rules = _load_rules_for(monkeypatch, eng, 5030760, 2296544770, 2207694412)
    assert rules == []


def test_marked_attr_only_rule_loads_as_unconditional_hide_with_f10_on(monkeypatch):
    """With F10 on, the now-resolved target lets the rule load -- as an
    unconditional (always=True) hide, since it genuinely has zero
    conditions. This is NOT scoped to "non-Federal customers"; that
    distinction belongs to cpq_rule_scope_filter_enabled + the rule's
    ref_id, which this loader doesn't apply."""
    eng = CpqEngine()
    with patch(
        "aryx.cpq.hiding_rules.type11.get_settings",
    ) as mock_settings:
        mock_settings.return_value.cpq_empty_condition_rule_true_enabled = True
        rules = _load_rules_for(monkeypatch, eng, 5030760, 2296544770, 2207694412)
    assert len(rules) == 1
    assert rules[0].always is True
    assert rules[0].hide is True
    assert rules[0].target_attr_id == 2207694412
