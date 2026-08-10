"""docs/CPQ_HIDDEN_MASTER_STRING_STALE_AFTER_CASCADE_PLAN_2026_08_10.md

evaluate_rules_loop caches `hiddenMasterStringForAstroPortable_astro` in `filled`
once computed, and only recomputed it when the key was entirely ABSENT --
never when the inputs it was derived from (productSelectionProduct_all,
modelSelectionbaseModel_astro) had since changed. Live bug: a mid-
conversation Hardware Version change cascades Product to a new value, but
the master string cached for the OLD product persists, so every hiding
rule keyed on it (e.g. Carrier Selection's) evaluates against the wrong
product and incorrectly hides a real, correctly-filled multi-select.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _make_hiding_rule_reading_master_string(target_id: int, marker: str) -> HidingRule:
    # The EXACT real "Hide Carrier Selection if no values available
    # (portables)" shape (Idiom D, evaluate_hide_master_list_unguarded) --
    # confirmed live this precise nested if/else form is required for
    # Tier-1 to parse it at all; a simplified single-if version matches no
    # supported idiom and always reports "unknown" regardless of the
    # master string's actual content, which would make this test pass for
    # the wrong reason.
    script = (
        f'splitstringArray = SPLIT(hiddenMasterStringForAstroPortable_astro,hidddenRecordSeparator_allFamilly);\n'
        f'valindex         = findinarray(splitstringArray,"{marker}");\n\n'
        'if(valindex ==-1){\n'
        ' return TRUE;\n'
        '}\n'
        'else{\n'
        ' if(modelSelectionbaseModel_astro==""){\n'
        '  return TRUE;\n'
        ' }\n'
        '}\n\n'
        'return FALSE;'
    )
    return HidingRule(
        rule_name="Hide unless in master string", target_attr_id=target_id,
        condition_attr_id=0, condition_value="", hide=True, script=script,
    )


def test_master_string_recomputed_when_product_changes_mid_conversation():
    target = ConfigAttr(
        entity_id=1, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier", required=False, default_value="",
        select_type="multi", options=_menu("ATT/FIRSTNET"),
    )
    hiding_rule = _make_hiding_rule_reading_master_string(1, "carrierSelectionMultiSelect_astro")

    call_products: list[str] = []

    def _fake_compute(self, filled, workspace_id, catalog_prefix, cache, attrs=None):
        product = filled.get("productSelectionProduct_all", "")
        call_products.append(product)
        # Product A's real sequence includes carrierSelectionMultiSelect_astro;
        # Product B's real sequence does NOT -- mirrors the real live shape
        # (governed for one product, not governed for another).
        if product == "PRODUCT_A":
            return "carrierSelectionMultiSelect_astro@@@otherAttr"
        return "otherAttr"

    eng = CpqEngine()
    filled = {
        "productSelectionProduct_all": "PRODUCT_A",
        "modelSelectionbaseModel_astro": "BASE1",
        "hidddenRecordSeparator_allFamilly": "@@@",
    }
    multi: dict[str, list[str]] = {}
    with patch.object(CpqEngine, "_compute_hidden_master_string", _fake_compute):
        visible_attrs, _, _, _ = eng.evaluate_rules_loop(
            [target], {}, filled, [hiding_rule], [], [],
            filled_multi=multi, workspace_id=7,
            bml_eval=BmlEvaluator(scripts={}, use_llm=False),
        )
    assert any(a.variable_name == "carrierSelectionMultiSelect_astro" for a in visible_attrs), (
        "product A's real master string includes this attr -- must stay visible"
    )
    assert call_products.count("PRODUCT_A") >= 1

    # Simulate a cascade: Hardware Version change forces Product to re-
    # resolve to a DIFFERENT value, in the SAME persisted `filled`/`multi`
    # dicts a real conversation would carry across the cascade.
    filled["productSelectionProduct_all"] = "PRODUCT_B"
    with patch.object(CpqEngine, "_compute_hidden_master_string", _fake_compute):
        visible_attrs2, filled2, _, _ = eng.evaluate_rules_loop(
            [target], {}, filled, [hiding_rule], [], [],
            filled_multi=multi, workspace_id=7,
            bml_eval=BmlEvaluator(scripts={}, use_llm=False),
        )
    assert not any(a.variable_name == "carrierSelectionMultiSelect_astro" for a in visible_attrs2), (
        "product B's real master string does NOT include this attr -- must "
        "now correctly hide, proving the cached (stale, product-A) master "
        "string was recomputed rather than reused"
    )
    assert "carrierSelectionMultiSelect_astro" not in multi, (
        "hidden attr's value must be cleared, not left dangling"
    )
    assert "PRODUCT_B" in call_products, "must have recomputed for the new product"


def test_master_string_not_recomputed_when_product_is_unchanged():
    target = ConfigAttr(
        entity_id=1, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier", required=False, default_value="",
        select_type="multi", options=_menu("ATT/FIRSTNET"),
    )
    hiding_rule = _make_hiding_rule_reading_master_string(1, "carrierSelectionMultiSelect_astro")

    call_count = [0]

    def _fake_compute(self, filled, workspace_id, catalog_prefix, cache, attrs=None):
        call_count[0] += 1
        return "carrierSelectionMultiSelect_astro"

    eng = CpqEngine()
    filled = {
        "productSelectionProduct_all": "PRODUCT_A",
        "modelSelectionbaseModel_astro": "BASE1",
        "hidddenRecordSeparator_allFamilly": "@@@",
    }
    multi: dict[str, list[str]] = {}
    with patch.object(CpqEngine, "_compute_hidden_master_string", _fake_compute):
        eng.evaluate_rules_loop(
            [target], {}, filled, [hiding_rule], [], [],
            filled_multi=multi, workspace_id=7,
            bml_eval=BmlEvaluator(scripts={}, use_llm=False),
        )
    first_call_count = call_count[0]
    assert first_call_count >= 1

    # Second, separate evaluate_rules_loop call (e.g. the next real /ask
    # turn) with NOTHING changed -- must reuse the cached value, not pay
    # the real Data Table lookup cost again.
    with patch.object(CpqEngine, "_compute_hidden_master_string", _fake_compute):
        eng.evaluate_rules_loop(
            [target], {}, filled, [hiding_rule], [], [],
            filled_multi=multi, workspace_id=7,
            bml_eval=BmlEvaluator(scripts={}, use_llm=False),
        )
    assert call_count[0] == first_call_count, (
        "must not recompute when product/base_model haven't changed -- "
        "the original 'compute once' optimization must survive this fix"
    )
