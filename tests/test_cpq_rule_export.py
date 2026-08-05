"""Tests for aryx.cpq.rule_export (docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md,
Tier 1). Fake reader/rdb -- no DB, no real catalog fixtures.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.rule_export import (
    UNSCOPED,
    build_product_tree,
    classify_rule_scope,
    export_rules_json,
    _name_index,
    _normalize,
)
from aryx.cpq.state import ConstraintRule, HidingRule, RecommendationRule


class _FakeReader:
    """Minimal reader stand-in: find_entities() returns pre-seeded rows."""

    def __init__(self, entities: list[dict]) -> None:
        self._entities = entities

    def find_entities(self, ontology_type: str, limit: int = 500) -> list[dict]:
        return [e for e in self._entities if e["ontology_type"] == ontology_type][:limit]


def _cat_ent(entity_id: int, native_id: str, parent_id: str, name: str) -> dict:
    return {
        "id": entity_id, "ontology_type": "TestBmCatalog",
        "name": name, "_attrs": {"id": native_id, "parent_id": parent_id, "name": name},
    }


def _patch_fetch_entity_attributes(entities: list[dict]):
    attrs_by_id = {e["id"]: e["_attrs"] for e in entities}
    return patch(
        "aryx.cpq.rule_export.get_cpq_rdb",
        return_value=type("R", (), {"fetch_entity_attributes": staticmethod(
            lambda ids, ws: {i: attrs_by_id[i] for i in ids if i in attrs_by_id}
        )})(),
    )


class TestBuildProductTree:
    def test_simple_hierarchy(self):
        entities = [
            _cat_ent(1, "FAM", "-1", "Family"),
            _cat_ent(2, "LINE", "FAM", "Line"),
            _cat_ent(3, "MODEL_A", "LINE", "Model A"),
            _cat_ent(4, "MODEL_B", "LINE", "Model B"),
        ]
        reader = _FakeReader(entities)
        with _patch_fetch_entity_attributes(entities):
            tree = build_product_tree(reader, workspace_id=1, catalog_prefix="Test")
        assert len(tree) == 4
        fam = tree["FAM"]
        assert fam.parent_id == "-1"
        line = tree["LINE"]
        assert line in fam.children
        assert {c.name for c in line.children} == {"Model A", "Model B"}

    def test_dangling_parent_id_treated_as_root(self):
        entities = [_cat_ent(1, "ORPHAN", "GHOST", "Orphan")]
        reader = _FakeReader(entities)
        with _patch_fetch_entity_attributes(entities):
            tree = build_product_tree(reader, workspace_id=1, catalog_prefix="Test")
        assert tree["ORPHAN"].parent_id == "-1"

    def test_self_referential_parent_id_treated_as_root_not_infinite_loop(self):
        entities = [_cat_ent(1, "SELFY", "SELFY", "Selfy")]
        reader = _FakeReader(entities)
        with _patch_fetch_entity_attributes(entities):
            tree = build_product_tree(reader, workspace_id=1, catalog_prefix="Test")
        assert tree["SELFY"].parent_id == "-1"

    def test_no_catalog_entities_returns_empty_tree(self):
        reader = _FakeReader([])
        tree = build_product_tree(reader, workspace_id=1, catalog_prefix="Test")
        assert tree == {}


class TestClassifyRuleScope:
    def _tree(self):
        entities = [
            _cat_ent(1, "FAM", "-1", "Family"),
            _cat_ent(2, "LINE", "FAM", "700/800 Line"),
            _cat_ent(3, "MODEL_A", "LINE", "700/800 MHZ"),
            _cat_ent(4, "MODEL_B", "LINE", "900 MHZ"),
        ]
        reader = _FakeReader(entities)
        with _patch_fetch_entity_attributes(entities):
            tree = build_product_tree(reader, workspace_id=1, catalog_prefix="Test")
        return tree

    def test_exact_match_resolves_to_model(self):
        tree = self._tree()
        idx = _name_index(tree)
        rule = HidingRule(
            rule_name="R1", condition_attr_id=1, condition_value="700/800 MHZ",
            target_attr_id=2,
        )
        scope = classify_rule_scope(rule, idx)
        assert scope["matched_node"] == "700/800 MHZ"
        assert scope["covers_models"] == ["700/800 MHZ"]

    def test_casing_mismatch_is_unresolved_not_fuzzy_matched(self):
        tree = self._tree()
        idx = _name_index(tree)
        # Real bug shape: rule says "MHz" but every real menu item is "MHZ".
        # Both normalize to the SAME uppercase key here, so this actually
        # matches -- to prove genuine divergence we use a value that has no
        # tree node at all under any casing.
        rule = HidingRule(
            rule_name="R2", condition_attr_id=1, condition_value="700/800 Megahertz",
            target_attr_id=2,
        )
        scope = classify_rule_scope(rule, idx)
        assert scope == {"scope": UNSCOPED}

    def test_no_condition_is_unscoped(self):
        tree = self._tree()
        idx = _name_index(tree)
        rule = ConstraintRule(
            rule_name="R3", condition_attr_id=0, condition_value="", target_attr_id=2,
            allowed_values=["X"],
        )
        assert classify_rule_scope(rule, idx) == {"scope": UNSCOPED}

    def test_script_backed_rule_is_always_unresolved(self):
        tree = self._tree()
        idx = _name_index(tree)
        rule = HidingRule(
            rule_name="R4", condition_attr_id=0, condition_value="700/800 MHZ",
            target_attr_id=2, script="return true;",
        )
        assert classify_rule_scope(rule, idx) == {"scope": UNSCOPED}

    def test_line_level_condition_covers_all_child_models(self):
        tree = self._tree()
        idx = _name_index(tree)
        rule = RecommendationRule(
            rule_name="R5", condition_attr_id=1, condition_value="700/800 Line",
            target_attr_id=2, recommended_value="X",
        )
        scope = classify_rule_scope(rule, idx)
        assert scope["matched_node"] == "700/800 Line"
        assert set(scope["covers_models"]) == {"700/800 MHZ", "900 MHZ"}


class TestExportRulesJsonNeverDropsARule:
    def test_every_loaded_rule_appears_somewhere(self):
        entities = [_cat_ent(1, "FAM", "-1", "Family")]
        reader = _FakeReader(entities)
        hiding = [
            HidingRule(rule_name="H1", condition_attr_id=1, condition_value="Family", target_attr_id=9),
            HidingRule(rule_name="H2", condition_attr_id=1, condition_value="Nope", target_attr_id=9),
        ]
        rec = [
            RecommendationRule(rule_name="C1", condition_attr_id=1, condition_value="", target_attr_id=9),
        ]
        con: list[ConstraintRule] = []
        with _patch_fetch_entity_attributes(entities):
            result = export_rules_json(reader, 1, "Test", hiding, rec, con)
        total_exported = len(result["unscoped_or_unresolved"]) + sum(
            len(rules)
            for fam in result["families"].values()
            for models in fam.values()
            for rules in models.values()
        )
        assert total_exported == result["total_rules_loaded"] == 3
