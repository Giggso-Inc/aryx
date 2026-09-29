"""Tests for _invalidate_stale_base_model — docs/CPQ_STALE_BASE_MODEL_
CASCADE_CONFLICT_PLAN_2026_08_20.md.

Unit-level, pure function: no DB, no rule evaluation. Confirms Base Model
is cleared exactly when the changed attribute or one of its cascade
dependents is Hardware Version, Product, Destination Country, or Region
(Base Model's own real derivation inputs, per engine.py:7958-7975), and
left untouched for any other change.

Also includes a pipeline-level integration test (below the unit tests) —
PR #235 review feedback: the unit tests above only prove the helper
clears `session.filled`, not that Base Model actually gets recomputed
correctly by the real rule-evaluation pipeline afterward. That test
drives the real `CpqEngine.evaluate_rules_loop` (which calls `auto_fill`,
where Base Model's own re-derivation logic lives, engine.py:7958-7975)
twice, mirroring the real two-turn shape: Hardware Version changes first
(Product and Base Model both go stale and get cleared), then Product is
answered (only then does Base Model's re-derivation have what it needs
-- a filled Product -- to resolve). It never resolves within the
Hardware-Version-change turn itself, by design (Base Model's own
derivation reads Product), so this test asserts what actually matters
for correctness: Base Model is never left holding its stale pre-change
value at either point, and resolves to the fresh, catalog-proven-correct
value once Product is answered.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model import _BASE_MODEL_VN, _invalidate_stale_base_model
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _attr(entity_id: int, variable_name: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=variable_name,
        display_label=variable_name, required=False, default_value="", options=[],
    )


def _session_with_base_model(value: str = "SOME_BASE_MODEL_CODE") -> CpqSession:
    return CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: value, "carrier": "Verizon"},
        display_filled={_BASE_MODEL_VN: value, "carrier": "Verizon"},
        filled_source={_BASE_MODEL_VN: "cascade", "carrier": "user"},
    )


def test_clears_base_model_when_changed_attr_is_hardware_version():
    session = _session_with_base_model()
    hw_version = _attr(1, "hWVersion_astro")
    _invalidate_stale_base_model(session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=1)
    assert _BASE_MODEL_VN not in session.filled
    assert _BASE_MODEL_VN not in session.display_filled
    assert _BASE_MODEL_VN not in session.filled_source


def test_clears_base_model_when_changed_attr_is_product():
    session = _session_with_base_model()
    product = _attr(2, "productSelectionProduct_all")
    _invalidate_stale_base_model(session, product, dependent_eids=set(), by_eid={}, workspace_id=1)
    assert _BASE_MODEL_VN not in session.filled


def test_clears_base_model_when_product_is_a_cascade_dependent():
    session = _session_with_base_model()
    hw_version = _attr(1, "hWVersion_astro")
    product = _attr(2, "productSelectionProduct_all")
    by_eid = {product.entity_id: product}
    _invalidate_stale_base_model(
        session, hw_version, dependent_eids={product.entity_id}, by_eid=by_eid,
        workspace_id=1,
    )
    assert _BASE_MODEL_VN not in session.filled


def test_clears_base_model_when_changed_attr_is_destination_country():
    session = _session_with_base_model()
    country = _attr(5, "ultimateDestinationCountry")
    _invalidate_stale_base_model(session, country, dependent_eids=set(), by_eid={}, workspace_id=1)
    assert _BASE_MODEL_VN not in session.filled


def test_clears_base_model_when_changed_attr_is_region():
    session = _session_with_base_model()
    region = _attr(6, "modelSelectionRegion_astro")
    _invalidate_stale_base_model(session, region, dependent_eids=set(), by_eid={}, workspace_id=1)
    assert _BASE_MODEL_VN not in session.filled


def test_clears_base_model_when_country_is_a_cascade_dependent():
    session = _session_with_base_model()
    some_other_attr = _attr(7, "someUpstreamAttr_astro")
    country = _attr(5, "ultimateDestinationCountry")
    by_eid = {country.entity_id: country}
    _invalidate_stale_base_model(
        session, some_other_attr, dependent_eids={country.entity_id}, by_eid=by_eid,
        workspace_id=1,
    )
    assert _BASE_MODEL_VN not in session.filled


def test_leaves_base_model_untouched_for_an_unrelated_change():
    session = _session_with_base_model()
    billing = _attr(3, "billingOption_astro")
    unrelated_dependent = _attr(4, "someOtherAttr_astro")
    by_eid = {unrelated_dependent.entity_id: unrelated_dependent}
    _invalidate_stale_base_model(
        session, billing, dependent_eids={unrelated_dependent.entity_id}, by_eid=by_eid,
        workspace_id=1,
    )
    assert session.filled[_BASE_MODEL_VN] == "SOME_BASE_MODEL_CODE"
    assert session.display_filled[_BASE_MODEL_VN] == "SOME_BASE_MODEL_CODE"
    assert session.filled_source[_BASE_MODEL_VN] == "cascade"


def test_noop_when_base_model_was_never_filled():
    session = CpqSession(
        product_name="APX NEXT XE", filled={"carrier": "Verizon"},
        display_filled={"carrier": "Verizon"}, filled_source={"carrier": "user"},
    )
    hw_version = _attr(1, "hWVersion_astro")
    _invalidate_stale_base_model(session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=1)
    assert _BASE_MODEL_VN not in session.filled


# ── Pipeline-level integration test (PR #235 review feedback) ───────────

_WORKSPACE_ID = 99001
_CATALOG_PREFIX = "TestAstro"
_CPQ_MODEL = "TESTFAMILY"


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _pipeline_attrs() -> list[ConfigAttr]:
    hw = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", options=_menu("HW_OLD", "HW_NEW"),
    )
    product = ConfigAttr(
        entity_id=2, variable_name="productSelectionProduct_all", display_label="Product",
        required=False, default_value="", options=_menu("PROD_OLD", "PROD_NEW"),
    )
    base_model = ConfigAttr(
        entity_id=3, variable_name=_BASE_MODEL_VN, display_label="Base Model",
        required=False, default_value="", options=_menu("BM_OLD", "BM_NEW"),
    )
    return [hw, product, base_model]


def _fake_load_all_tables(*_args, **_kwargs):
    """Minimal, synthetic Data Tables (data_table_resolver._load_all_
    tables' 5-tuple shape) proving the real thing an actual ingested
    catalog would carry: PROD_NEW resolves to _CPQ_MODEL (so
    resolve_product_cpq_models_from_rows can find it), and a region-rule
    row gives Base Model exactly one real ALLOW value for that model in
    the NA region -- the same mechanism resolve_region_allow_value's own
    docstring cites for the real APX NEXT catalog."""
    constraint_rows = [
        {
            "CPQModel": _CPQ_MODEL, "BaseModel": "BM_NEW",
            "attr1": "hWVersion_astro", "val1": "HW_NEW",
            "attr2": "productSelectionProduct_all", "val2": "PROD_NEW",
        },
    ]
    region_rule_rows = [
        {
            "attribute": _BASE_MODEL_VN, "model": _CPQ_MODEL, "region": "NA",
            "ruleType": "ALLOW", "value": "BM_NEW", "UDCC": "",
        },
    ]
    return constraint_rows, [], [], [], region_rule_rows


def test_base_model_is_never_stale_across_a_real_two_turn_cascade():
    """Turn 1: Hardware Version changes HW_OLD -> HW_NEW (Product and Base
    Model both cleared by the fix, mirroring _handle_cascade's real
    invalidation step). Turn 2: Product is answered PROD_NEW. Runs the
    REAL evaluate_rules_loop/auto_fill pipeline both times -- not just the
    helper in isolation -- and asserts Base Model is never left holding
    its stale HW_OLD-era value (BM_OLD) at any point, resolving instead to
    the fresh, catalog-proven-correct BM_NEW once Product allows it to."""
    attrs = _pipeline_attrs()
    con_rules = [
        ConstraintRule(
            rule_name="hw_gates_product", condition_attr_id=1, condition_value="HW_NEW",
            target_attr_id=2, allowed_values=["PROD_NEW"],
        ),
    ]
    engine = CpqEngine()
    session = CpqSession(
        product_name="Test Product",
        filled={"hWVersion_astro": "HW_OLD", "productSelectionProduct_all": "PROD_OLD",
                _BASE_MODEL_VN: "BM_OLD"},
        display_filled={"hWVersion_astro": "HW_OLD", "productSelectionProduct_all": "PROD_OLD",
                         _BASE_MODEL_VN: "BM_OLD"},
        filled_source={"hWVersion_astro": "user", "productSelectionProduct_all": "user",
                       _BASE_MODEL_VN: "cascade"},
        country="United States",
    )
    hw_attr = attrs[0]
    by_eid = {a.entity_id: a for a in attrs}

    with patch("aryx.cpq.data_table.data_table_product._load_all_tables", side_effect=_fake_load_all_tables):
        # Turn 1 — Hardware Version changes; mirrors _handle_cascade's own
        # dependent-stripping + _invalidate_stale_base_model call.
        dependent_eids = engine.find_cascade_dependents(hw_attr, attrs, [], [], con_rules)
        session.filled.pop("hWVersion_astro", None)
        session.filled["hWVersion_astro"] = "HW_NEW"
        for eid in dependent_eids:
            a = by_eid.get(eid)
            if a:
                session.filled.pop(a.variable_name, None)
        _invalidate_stale_base_model(session, hw_attr, dependent_eids, by_eid, _WORKSPACE_ID, _CATALOG_PREFIX)
        assert "productSelectionProduct_all" not in session.filled
        assert _BASE_MODEL_VN not in session.filled, (
            "Base Model must not still be BM_OLD after Hardware Version changes"
        )

        _, filled, _, _ = engine.evaluate_rules_loop(
            attrs, {}, session.filled, [], [], con_rules,
            filled_source=session.filled_source, country=session.country,
            workspace_id=_WORKSPACE_ID, catalog_prefix=_CATALOG_PREFIX,
        )
        session.filled = filled
        # Base Model's own re-derivation reads Product (engine.py:7958) --
        # Product isn't answered yet this turn, so it correctly stays
        # unresolved. The property that matters: never the stale value.
        assert session.filled.get(_BASE_MODEL_VN) != "BM_OLD"

        # Turn 2 — Product answered.
        session.filled["productSelectionProduct_all"] = "PROD_NEW"
        session.filled_source["productSelectionProduct_all"] = "user"
        _, filled, _, _ = engine.evaluate_rules_loop(
            attrs, {}, session.filled, [], [], con_rules,
            filled_source=session.filled_source, country=session.country,
            workspace_id=_WORKSPACE_ID, catalog_prefix=_CATALOG_PREFIX,
        )
        session.filled = filled

    assert session.filled.get(_BASE_MODEL_VN) == "BM_NEW", (
        f"expected Base Model to resolve to the fresh, correct BM_NEW once "
        f"Product was answered; got {session.filled.get(_BASE_MODEL_VN)!r} "
        f"instead -- if this is BM_OLD, the stale value survived the cascade"
    )
