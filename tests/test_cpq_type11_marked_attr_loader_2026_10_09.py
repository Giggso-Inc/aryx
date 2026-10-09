"""Loader-level pin for the `_rule_key`/`marked` fix (rule_targets.py) --
review-requested (2026-10-09) because the four `_rule_key`-only tests in
test_cpq_rule_key_marked_attr_resolution_2026_10_09.py never exercise
`_load_type11_hiding_rules`, so "rule now hides FCC for APX 1500 Enhanced"
was unverified.

Exercises `_load_type11_hiding_rules` directly for a no-input/no-action,
marked-attr-only, declarative rule (the live shape of ws 1267 rule 5030760
"Hide do you required Radio FED FCC", `ref_id="903471941"` -> BmCatalog node
`aPXNext`). See docs/cpq/CPQ_RULE_KEY_MARKED_ATTR_RESOLUTION_2026_10_09.md
for the full investigation:

- F10 (`cpq_empty_condition_rule_true_enabled`) off: still dropped as
  "unresolved" -- the fix alone changes nothing while F10 stays off (ws
  1267's real default), whatever the scope filter is set to.
- F10 on, rule UNBOUND (no ref_id): loads as an unconditional (always=True)
  hide -- it was never scoped to begin with, nothing to misapply.
- F10 on, rule scoped to a real node: REFUSED to load as always=True --
  review round 3 (2026-10-09) made this refusal structural, deliberately
  NOT conditioned on `cpq_rule_scope_filter_enabled`'s value. This loader
  runs once per workspace/catalog, cached and shared across every turn and
  product, with no per-turn resolved-model context to check the rule's
  ref_id against -- so whether the scope filter happens to be on, and
  whether a later turn's model even has a non-empty scope to check it
  against, are both unknowable here. A node-scoped, zero-condition rule is
  therefore refused every time, regardless of either flag.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.hiding_rules.type11 import _load_type11_hiding_rules

_RULE_NAME = "Hide do you required Radio FED FCC"
_REAL_REF_ID = "903471941"  # the aPXNext BmCatalog node, confirmed live


def _fake_rdb_marked_attr_only(entity_id: int, source_id: int, ref_id: str):
    """A minimal rdb double: one declarative hiding rule (rule_type=11, no
    script) with zero BmConfigRuleInput/Action rows -- its only target
    linkage is a BmConfigMarkedAttr row keyed under `source_id`, matching
    rule 5030760's real shape exactly."""

    def _fetch_rules(workspace_id, rule_type, catalog_prefix="", active_only=False, **_kw):
        assert rule_type == "11"
        return [(entity_id, source_id, _RULE_NAME, -1, ref_id)]  # fn_id=-1: declarative, not script

    return type("R", (), {
        "fetch_rules": staticmethod(_fetch_rules),
        "fetch_function_scripts": staticmethod(lambda *a, **k: {}),
    })()


def _load_rules_for(
    monkeypatch, eng, entity_id: int, source_id: int, target_attr_id: int,
    *, f10: bool, scope_filter: bool, ref_id: str = _REAL_REF_ID,
):
    """Calls `_load_type11_hiding_rules` directly -- NOT `eng.load_hiding_
    rules` -- so this test pins only the `_rule_key`/F10/scope-trap
    interaction this PR touches. `load_hiding_rules` additionally runs
    `rule_scope.scope_rules_by_ancestry` and merges in `_load_value_rules`'
    value-less hiding rules; both are separate, already-existing concerns
    this test deliberately does not exercise. Both flags are controlled
    explicitly here rather than relying on this test environment's own
    config defaults (confirmed live to default `cpq_rule_scope_filter_
    enabled` to True, unlike ws 1267's dev container)."""
    fake_rdb = _fake_rdb_marked_attr_only(entity_id, source_id, ref_id)

    def _fake_load_rule_join_data(workspace_id, catalog_prefix):
        inputs: dict = {}
        actions: dict = {}
        marked = {source_id: [target_attr_id]}  # keyed under source_id, not entity_id -- the real shape
        chain: dict = {}
        return fake_rdb, inputs, actions, marked, chain

    monkeypatch.setattr(eng, "_load_rule_join_data", _fake_load_rule_join_data)
    with (
        patch("aryx.cpq.hiding_rules.type11.get_settings") as mock_settings,
        patch("aryx.cpq.rule_scope.rule_scope_enabled", return_value=scope_filter),
    ):
        mock_settings.return_value.cpq_empty_condition_rule_true_enabled = f10
        return _load_type11_hiding_rules(eng, 1267, "", 0.0, "")


def test_marked_attr_only_rule_still_dropped_with_f10_off(monkeypatch):
    """The real ws 1267 dev state (confirmed live 2026-10-09): F10 defaults
    off, so even though the target now resolves, the rule's empty input list
    still makes it 'unresolved' and it is still dropped -- this fix alone
    does not change behavior while F10 stays off, whatever the scope filter
    is set to."""
    for scope_filter in (True, False):
        eng = CpqEngine()
        rules = _load_rules_for(
            monkeypatch, eng, 5030760, 2296544770, 2207694412,
            f10=False, scope_filter=scope_filter,
        )
        assert rules == []


def test_unbound_unconditional_rule_loads_with_f10_on_regardless_of_scope_filter(monkeypatch):
    """An UNBOUND rule (no ref_id) was never scoped to begin with, so there
    is nothing it could misapply to -- it loads as always=True under F10
    whether the scope filter is on or off."""
    for scope_filter in (True, False):
        eng = CpqEngine()
        rules = _load_rules_for(
            monkeypatch, eng, 5030760, 2296544770, 2207694412,
            f10=True, scope_filter=scope_filter, ref_id="",
        )
        assert len(rules) == 1
        assert rules[0].always is True
        assert rules[0].hide is True
        assert rules[0].target_attr_id == 2207694412


def test_scoped_unconditional_rule_refused_with_f10_on_regardless_of_scope_filter(monkeypatch):
    """Review round 3 (2026-10-09): a node-scoped, zero-condition rule is
    refused structurally -- NOT conditioned on `cpq_rule_scope_filter_
    enabled`'s value. This loader has no per-turn resolved-model context to
    check the rule's ref_id against, so it can't tell whether the scope
    filter being on would actually confine this rule correctly (round 2's
    empty-scope_node_ids case) or not at all (round 2 only covers the
    filter-on-but-empty-scope case, not filter-off). Refusing every time,
    regardless of either flag, is the only signal-independent safe answer."""
    for scope_filter in (True, False):
        eng = CpqEngine()
        rules = _load_rules_for(
            monkeypatch, eng, 5030760, 2296544770, 2207694412,
            f10=True, scope_filter=scope_filter, ref_id=_REAL_REF_ID,
        )
        assert rules == []


def test_family_level_ref_id_sentinel_also_loads_as_unconditional(monkeypatch):
    """Control: a ref_id of "-1" (the family-level/root sentinel, matching
    rule_scope.py's own "unbound" treatment) is not a real node either --
    it loads as always=True, same as a genuinely empty ref_id."""
    eng = CpqEngine()
    rules = _load_rules_for(
        monkeypatch, eng, 5030760, 2296544770, 2207694412,
        f10=True, scope_filter=True, ref_id="-1",
    )
    assert len(rules) == 1
    assert rules[0].always is True
