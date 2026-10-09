"""Regression test for the stale-target-resolution bug found live on
workspace 1267 (2026-10-09): the declarative hiding rule "Hide do you
required Radio FED FCC" (entity_id=5030760, source_id=2296544770) has no
BmConfigRuleInput condition row and no BmConfigRuleAction row -- its only
target linkage is a BmConfigMarkedAttr row keyed under `source_id`, not
`entity_id`. `_rule_key()` only checked inputs/actions, so with neither id
present there it fell back to `entity_id`, and `_resolve_targets(entity_id,
...)` then missed the real marked_attr row -- the rule was dropped as having
"no resolvable target" even though one exists, which is why "Do You Require
Radio FCC Trigger?" was never hidden for APX 1500 Enhanced.

Its sibling "APX5000 Hide do you required Radio FED FCC" (same shape) has
also carried a condition row under `source_id`, which let the original
`_rule_key()` pick the right id by coincidence -- confirming this is a real
resolution gap, not specific to one rule.
"""
from __future__ import annotations

from aryx.cpq.layout_and_join_data.rule_targets import _resolve_targets, _rule_key


def test_rule_key_prefers_source_id_when_only_marked_attr_references_it():
    """The actual bug: a rule with no input/action row under either id, but a
    marked_attr row under source_id, must resolve to source_id once `marked`
    is passed -- not fall back to entity_id."""
    entity_id, source_id = 5030760, 2296544770
    inputs: dict = {}
    actions: dict = {}
    marked = {source_id: [2207694412]}

    key = _rule_key(entity_id, source_id, inputs, actions, marked)
    assert key == source_id

    targets = _resolve_targets(key, actions, marked, {})
    assert targets == [(2207694412, 2)]


def test_rule_key_without_marked_argument_keeps_old_behavior():
    """Positive control: omitting `marked` (every pre-existing caller) must
    behave exactly as before -- falls back to entity_id, the rule stays
    unresolved. Confirms the fix doesn't change behavior for callers that
    don't resolve marked-attr targets (e.g. value_rules_load)."""
    entity_id, source_id = 5030760, 2296544770
    inputs: dict = {}
    actions: dict = {}
    marked = {source_id: [2207694412]}

    key = _rule_key(entity_id, source_id, inputs, actions)
    assert key == entity_id

    targets = _resolve_targets(key, actions, marked, {})
    assert targets == []


def test_rule_key_still_prefers_source_id_when_input_or_action_references_it():
    """Control: the original signal (source_id in inputs/actions) still wins,
    whether or not `marked` is also passed."""
    entity_id, source_id = 1, 2
    inputs = {source_id: [(10, "US", "1")]}
    actions: dict = {}

    assert _rule_key(entity_id, source_id, inputs, actions) == source_id
    assert _rule_key(entity_id, source_id, inputs, actions, {}) == source_id


def test_rule_key_falls_back_to_entity_id_when_marked_only_references_entity_id():
    """Control: when the marked_attr row is keyed under entity_id (the more
    common shape per rule_join.py's docstring), entity_id is already correct
    and stays the answer."""
    entity_id, source_id = 5033638, 2640647076
    inputs: dict = {}
    actions: dict = {}
    marked = {entity_id: [99]}

    assert _rule_key(entity_id, source_id, inputs, actions, marked) == entity_id


def test_rule_key_never_flips_away_from_a_real_condition_kept_under_entity_id():
    """Review-confirmed risk (2026-10-09): a rule whose real condition is
    keyed under entity_id must not flip to source_id just because source_id
    also happens to appear in marked (an unrelated marked-attr row). Flipping
    would silently drop the real condition -- marked is a fallback for when
    NEITHER id has a condition/action, never an equal-priority signal."""
    entity_id, source_id = 1, 2
    inputs = {entity_id: [(10, "US", "1")]}
    actions: dict = {}
    marked = {source_id: [99]}

    assert _rule_key(entity_id, source_id, inputs, actions, marked) == entity_id


def test_rule_key_marked_fallback_does_not_apply_when_entity_id_is_also_marked():
    """When both ids appear in marked (or only entity_id does), entity_id --
    the more common shape -- wins; the source_id fallback is for the narrow
    case where entity_id has no linkage at all."""
    entity_id, source_id = 1, 2
    inputs: dict = {}
    actions: dict = {}
    marked = {entity_id: [99], source_id: [100]}

    assert _rule_key(entity_id, source_id, inputs, actions, marked) == entity_id
