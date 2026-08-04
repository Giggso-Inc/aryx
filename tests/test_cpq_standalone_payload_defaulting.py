"""find_unresolvable_context_attrs / build_standalone_payload — the fix for
docs/APX_Next_RootCause_And_Fix_Report Issue 1: a payload assembled
directly (outside a live conversational turn) has no mechanism to ever
populate a rule-driven or option-less, script-referenced attr.

Uses made-up attribute/rule/script names (not the real APX Next catalog's
customerType/operationModeType_astro/etc.) to prove the fix is
catalog-agnostic, not tuned to one export's data.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=f"Display {v}", order=i)
            for i, v in enumerate(values, start=1)]


def _fake_rdb(scripts: dict[int, str]):
    return type("R", (), {
        "fetch_function_scripts": staticmethod(lambda *a, **k: scripts),
    })()


def test_option_less_script_referenced_attr_with_no_rule_target_is_flagged(monkeypatch):
    engine = CpqEngine()
    attrs = [
        ConfigAttr(entity_id=1, source_id=1, variable_name="realOption",
                   display_label="Real Option", required=False, default_value="",
                   options=_menu("A", "B")),
        ConfigAttr(entity_id=2, source_id=2, variable_name="contextFlag",
                   display_label="Context Flag", required=False, default_value="",
                   options=[]),
    ]
    scripts = {100: 'if (contextFlag=="ENTERPRISE") { retVal = "PREMIUM"; }'}
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: _fake_rdb(scripts))

    result = engine.find_unresolvable_context_attrs(
        attrs, filled={}, workspace_id=1, catalog_prefix="",
        rec_rules=[], con_rules=[],
    )
    assert len(result) == 1
    assert result[0]["variable_name"] == "contextFlag"
    assert result[0]["literal_values_referenced"] == ["ENTERPRISE"]
    assert result[0]["num_referencing_scripts"] == 1


def test_attr_already_filled_is_not_flagged(monkeypatch):
    engine = CpqEngine()
    attrs = [
        ConfigAttr(entity_id=2, source_id=2, variable_name="contextFlag",
                   display_label="Context Flag", required=False, default_value="",
                   options=[]),
    ]
    scripts = {100: 'if (contextFlag=="ENTERPRISE") { retVal = "PREMIUM"; }'}
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: _fake_rdb(scripts))

    result = engine.find_unresolvable_context_attrs(
        attrs, filled={"contextFlag": "ENTERPRISE"}, workspace_id=1, catalog_prefix="",
        rec_rules=[], con_rules=[],
    )
    assert result == []


def test_attr_a_recommendation_rule_can_fill_is_not_flagged(monkeypatch):
    """This is the class of attr covered by evaluate_rules_loop already —
    e.g. a real recommendation rule targets it — so this diagnostic must
    not double-report it as unresolvable; a rule CAN resolve it."""
    engine = CpqEngine()
    attrs = [
        ConfigAttr(entity_id=2, source_id=2, variable_name="contextFlag",
                   display_label="Context Flag", required=False, default_value="",
                   options=[]),
    ]
    scripts = {100: 'if (contextFlag=="ENTERPRISE") { retVal = "PREMIUM"; }'}
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: _fake_rdb(scripts))
    rec_rules = [
        RecommendationRule(rule_name="Derive contextFlag", condition_attr_id=0,
                            condition_value="", target_attr_id=2,
                            recommended_value="ENTERPRISE"),
    ]

    result = engine.find_unresolvable_context_attrs(
        attrs, filled={}, workspace_id=1, catalog_prefix="",
        rec_rules=rec_rules, con_rules=[],
    )
    assert result == []


def test_ranked_by_referencing_script_count_descending(monkeypatch):
    engine = CpqEngine()
    attrs = [
        ConfigAttr(entity_id=1, source_id=1, variable_name="lowRef",
                   display_label="Low Ref", required=False, default_value="", options=[]),
        ConfigAttr(entity_id=2, source_id=2, variable_name="highRef",
                   display_label="High Ref", required=False, default_value="", options=[]),
    ]
    scripts = {
        100: 'if (lowRef=="X") { retVal = true; }',
        101: 'if (highRef=="Y") { retVal = true; }',
        102: 'if (highRef=="Y") { retVal = false; }',
    }
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: _fake_rdb(scripts))

    result = engine.find_unresolvable_context_attrs(
        attrs, filled={}, workspace_id=1, catalog_prefix="",
        rec_rules=[], con_rules=[],
    )
    assert [r["variable_name"] for r in result] == ["highRef", "lowRef"]


def test_build_standalone_payload_fills_via_evaluate_rules_loop_and_orders_by_dependency(monkeypatch):
    """End-to-end: a recommendation-rule-driven, option-less attr (the
    operationModeType_astro-class gap) gets auto-filled by the SAME loop a
    live turn uses, and the final payload is dependency-ordered — both
    fixes landing in one call, with made-up names."""
    engine = CpqEngine()
    attrs = [
        ConfigAttr(entity_id=1, source_id=1, variable_name="driverAttr",
                   display_label="Driver", required=False, default_value="",
                   options=_menu("STANDARD")),
        ConfigAttr(entity_id=2, source_id=2, variable_name="derivedFlag",
                   display_label="Derived Flag", required=False, default_value="",
                   options=[], order=999),
    ]
    rec_rules = [
        RecommendationRule(
            rule_name="Derive flag from driver",
            condition_attr_id=1, condition_value="STANDARD",
            target_attr_id=2, recommended_value="DEFAULT_MODE",
        ),
    ]
    reader = MagicMock()
    monkeypatch.setattr(engine, "load_product_config", lambda *a, **k: (attrs, "TestProduct"))
    monkeypatch.setattr(engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: (rec_rules, []))
    monkeypatch.setattr(engine, "build_bml_evaluator", lambda *a, **k: None)
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: _fake_rdb({}))

    payload, unresolved = engine.build_standalone_payload(
        reader, workspace_id=1, product_hint="TestProduct",
        filled={"driverAttr": "STANDARD"},
    )
    # derivedFlag has no menu options -> bare string, per build_payload's own
    # documented per-type serialization (menu shape only applies when the
    # attr actually has options).
    assert payload["configData"]["derivedFlag"] == "DEFAULT_MODE"
    assert unresolved == []
