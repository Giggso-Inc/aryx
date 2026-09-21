"""docs/APX900_Hybrid_Combiner_Missing_Script_Issue.md:

'Hide Optional Peripherals 900 MHz Hybrid Combiner For G Series If No Value
Available' hiding rule's own BmFunction script was never ingested --
load_hiding_rules previously dropped the rule entirely (script_missing
branch), so op900MHzHybridCombiner_astro was asked unconditionally with a
blind-filled default for every product in the shared aSTRO25 family,
including APX 900 configurations where it has no legal value yet.

Fix: this one, explicitly-named rule is kept (not dropped) with
dt_whitelist_substitute=True; apply_hiding_rules substitutes a real Data
Table whitelist check (resolve_whitelist_values) for the missing script --
hides only when that CONFIRMS no legal value ([] exactly, never None, which
means "no Data Table coverage at all" and must not be treated as confirmed
empty).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, HidingRule

_RULE_NAME = (
    "Hide Optional Peripherals 900 MHz Hybrid Combiner For G Series "
    "If No Value Available"
)


def _fake_rdb_missing_script(rule_name: str, target_attr_id: int = 501):
    """A minimal rdb double: one hiding rule (rule_type=11, script-backed)
    whose BmFunction script is absent from fetch_function_scripts."""

    def _fetch_rules(workspace_id, rule_type, catalog_prefix="", active_only=False):
        assert rule_type == "11"
        return [(9001, 8001, rule_name, 777)]  # eid, src_id, rule_name, fn_id

    return type("R", (), {
        "fetch_rules": staticmethod(_fetch_rules),
        "fetch_function_scripts": staticmethod(lambda *a, **k: {}),  # 777 absent
    })()


def _load_rules_for(monkeypatch, eng, rule_name: str, target_attr_id: int = 501):
    fake_rdb = _fake_rdb_missing_script(rule_name, target_attr_id)

    def _fake_load_rule_join_data(workspace_id, catalog_prefix):
        inputs: dict = {}
        # actions_by_rule[rule_key] -> [(target_attr_id, action_type, value,
        # function_id, set_type, comments)] -- see _resolve_targets' own
        # unpacking. rule_key resolves to source_id (8001) here since it's
        # present in this dict (see _rule_key).
        actions = {8001: [(target_attr_id, 2, "", -1, -1, "")]}
        marked: dict = {}
        chain: dict = {}
        return fake_rdb, inputs, actions, marked, chain

    monkeypatch.setattr(eng, "_load_rule_join_data", _fake_load_rule_join_data)
    return eng.load_hiding_rules(workspace_id=97, catalog_prefix="Astro25Configdata")


def test_named_rule_is_kept_with_dt_whitelist_substitute_not_dropped(monkeypatch):
    eng = CpqEngine()
    rules = _load_rules_for(monkeypatch, eng, _RULE_NAME)

    assert len(rules) == 1, (
        "the confirmed-named rule must be KEPT (not silently dropped) even "
        "though its BmFunction script is missing"
    )
    assert rules[0].dt_whitelist_substitute is True
    assert rules[0].script is None


def test_unrelated_missing_script_rule_is_still_dropped(monkeypatch):
    """No regression: only the one confirmed, explicitly-named rule gets
    the substitute -- every other missing-script hiding rule keeps today's
    existing (drop-it) behavior."""
    eng = CpqEngine()
    rules = _load_rules_for(monkeypatch, eng, "Hide Some Unrelated Attribute If No Value Available")

    assert rules == [], (
        "an unrelated rule with a missing script must still be dropped -- "
        "this fix is a narrow, named carve-out, not a generic pattern match"
    )


def _combiner_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=501, variable_name="op900MHzHybridCombiner_astro",
        display_label="900 MHz Hybrid Combiner", required=False,
        default_value="single output 2-way", options=[], source_id=8501,
    )


def test_hides_when_resolve_whitelist_values_confirms_empty(monkeypatch):
    """resolve_whitelist_values returning [] (confirmed no legal value under
    the current context) must hide the attribute."""
    eng = CpqEngine()
    attr = _combiner_attr()
    rule = HidingRule(
        rule_name=_RULE_NAME, condition_attr_id=0, condition_value="",
        target_attr_id=attr.entity_id, dt_whitelist_substitute=True,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine._cpq_model_candidates",
        lambda *a, **k: ("SOMECPQMODEL",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        lambda *a, **k: [],
    )
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        [attr], {"modelSelectionbaseModel_astro": "SOMEBASEMODEL"}, [rule],
        workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert attr.variable_name in hidden_vns
    assert attr not in visible


def test_does_not_hide_when_resolve_whitelist_values_returns_none(monkeypatch):
    """None means 'no Data Table coverage at all' -- genuinely unknown, NOT
    confirmed empty. Must NOT be treated as a reason to hide (never guess)."""
    eng = CpqEngine()
    attr = _combiner_attr()
    rule = HidingRule(
        rule_name=_RULE_NAME, condition_attr_id=0, condition_value="",
        target_attr_id=attr.entity_id, dt_whitelist_substitute=True,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine._cpq_model_candidates",
        lambda *a, **k: ("SOMECPQMODEL",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        lambda *a, **k: None,
    )
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        [attr], {"modelSelectionbaseModel_astro": "SOMEBASEMODEL"}, [rule],
        workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert attr.variable_name not in hidden_vns
    assert attr in visible


def test_does_not_hide_when_a_real_legal_value_exists(monkeypatch):
    eng = CpqEngine()
    attr = _combiner_attr()
    rule = HidingRule(
        rule_name=_RULE_NAME, condition_attr_id=0, condition_value="",
        target_attr_id=attr.entity_id, dt_whitelist_substitute=True,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine._cpq_model_candidates",
        lambda *a, **k: ("SOMECPQMODEL",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        lambda *a, **k: ["SINGLE OUTPUT 2-WAY"],
    )
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        [attr], {"modelSelectionbaseModel_astro": "SOMEBASEMODEL"}, [rule],
        workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert attr.variable_name not in hidden_vns
    assert attr in visible


def test_does_not_hide_without_workspace_id_or_base_model_same_as_today(monkeypatch):
    """No workspace_id (or no base_model filled yet) -- can't check the
    Data Table at all. Must fall back to the exact same 'leave visible'
    default as today's behavior (before this fix existed), never hide
    more aggressively for lack of context."""
    eng = CpqEngine()
    attr = _combiner_attr()
    rule = HidingRule(
        rule_name=_RULE_NAME, condition_attr_id=0, condition_value="",
        target_attr_id=attr.entity_id, dt_whitelist_substitute=True,
    )
    visible, _msgs, hidden_vns = eng.apply_hiding_rules(
        [attr], {}, [rule],  # no workspace_id passed, no base_model filled
    )
    assert attr.variable_name not in hidden_vns
    assert attr in visible
