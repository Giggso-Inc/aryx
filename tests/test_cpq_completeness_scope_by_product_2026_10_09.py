"""Product-level scope for the completeness check (flag `cpq_completeness_scope_by_product_enabled`).

ws 1267: APX 8000 / 6000 stop at the first message on 'missing required data: Is FLASHcode Available?, Quantity, Power Adapter',
attributes of the flash-upgrade and ASTRO systems flows that no sequence row of these models lists."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.api.ask_stale_constraint import ask_completeness_scope as scope
from aryx.cpq.state import ConfigAttr

FLASH = "isFLASHcodeAvailable_astro"
POWER = "powerAdapter_astro"
KEYPAD = "modelSelectionKeypadType_astro"
COUNTRY = "ultimateDestinationCountry"
ROWS = [{"CPQModel": "APX8000", "BaseModel": "A", "AttrName": KEYPAD},
        {"CPQModel": "APX8000", "BaseModel": "B", "AttrName": "antennasType_astro"},
        {"CPQModel": "OTHERMODEL", "BaseModel": "Z", "AttrName": FLASH}]


def _attr(vn, hidden=False):
    return ConfigAttr(entity_id=abs(hash(vn)) % 99999, variable_name=vn, display_label=vn, required=True, default_value="",
                      select_type="single", hidden=hidden, options=[])


ATTRS = [_attr(FLASH), _attr(POWER), _attr(KEYPAD), _attr(COUNTRY), _attr("antennasType_astro")]


def _run(flag, filled=None, candidates=("APX8000",), rows=ROWS, sources=None, product="APX 8000"):
    session = SimpleNamespace(filled={"productSelectionProduct_all": product, **(filled or {})},
                              filled_source=sources or {}, product_name=product)
    engine = SimpleNamespace(_cpq_model_candidates=lambda *a, **k: candidates)
    with patch.object(scope, "get_settings", return_value=SimpleNamespace(cpq_completeness_scope_by_product_enabled=flag)), \
            patch.object(scope, "resolve_base_model_vn", return_value="baseModel"), \
            patch.object(scope, "_load_all_tables", return_value=(None, rows)):
        return [a.variable_name for a in scope.product_scoped_attrs(engine, ATTRS, session, 1267, "p")]


def test_flag_off_changes_nothing():
    assert _run(False) == [a.variable_name for a in ATTRS]


def test_attributes_no_base_model_of_the_product_lists_are_left_out_of_the_check():
    got = _run(True)
    assert FLASH not in got and POWER not in got                       # no APX8000 row lists them
    assert KEYPAD in got and "antennasType_astro" in got               # listed by a base model of the product


def test_anchors_and_attributes_with_a_customer_value_are_kept():
    got = _run(True, filled={POWER: "YES"}, sources={POWER: "user"})
    assert COUNTRY in got and POWER in got and FLASH not in got


def test_a_known_base_model_leaves_the_list_to_the_base_model_scoping():
    assert _run(True, filled={"baseModel": "H59UCD9PW4AN"}) == [a.variable_name for a in ATTRS]


def test_a_product_without_sequence_rows_is_untouched():
    assert _run(True, candidates=("NOROWS",)) == [a.variable_name for a in ATTRS]


def test_a_failure_returns_the_full_list():
    session = SimpleNamespace(filled={"productSelectionProduct_all": "APX 8000"}, filled_source={}, product_name="x")
    engine = SimpleNamespace(_cpq_model_candidates=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with patch.object(scope, "get_settings", return_value=SimpleNamespace(cpq_completeness_scope_by_product_enabled=True)), \
            patch.object(scope, "resolve_base_model_vn", return_value="baseModel"):
        assert scope.product_scoped_attrs(engine, ATTRS, session, 1267, "p") == ATTRS


def test_the_completeness_check_uses_the_product_scoped_list():
    from aryx.api.ask_stale_constraint import ask_stale_constraint_reask as reask
    kept = [ATTRS[2]]
    session = SimpleNamespace(filled={}, filled_source={}, product_name="APX 8000")
    with patch("aryx.api.ask_stale_constraint.ask_completeness_scope.product_scoped_attrs", return_value=kept), \
            patch("aryx.cpq.model_scoping_flags.scoped_questions_enabled", return_value=False):
        assert reask._applicable_attrs(SimpleNamespace(), ATTRS, session, 1267, "p") == kept
