"""Beautify drops rows of attributes the request's rules loop hid by rule (cpq_beautify_hide_rule_hidden_enabled).

ws 1267, APX N70: Operation Type (Defaultinattr default) and Provisioning Assistance (auto) were shown in Beautify
although the real screen hides them. Beautify is built over the whole catalog without re-running the hiding rules;
the loop now records what its hiding rules removed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.rules_loop import full_attrs_registry, rules_loop
from aryx.cpq.state import ConfigAttr


@pytest.fixture
def flag():
    s = get_settings()
    previous = s.cpq_beautify_hide_rule_hidden_enabled
    s.cpq_beautify_hide_rule_hidden_enabled = True
    full_attrs_registry._clear()
    yield s
    s.cpq_beautify_hide_rule_hidden_enabled = previous
    full_attrs_registry._clear()


def _attr(eid: int, vn: str, label: str, hidden: bool = False) -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=label, required=False, default_value="",
                      options=[], hidden=hidden)


ATTRS = [_attr(1, "operationModeType_astro", "Operation Type"), _attr(2, "beltClipType_astro", "Carry Type")]
FILLED = {"operationModeType_astro": "Digital Trunking", "beltClipType_astro": "2.5 Inch"}


def _labels(rows):
    return {r["label"] for r in rows}


def _rows(sources=None):
    return CpqEngine().beautify_rows("APX N70", FILLED, ATTRS, sources or {}, workspace_id=1267, catalog_prefix="astro")


def test_flag_off_shows_the_rule_hidden_row():
    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    assert "Operation Type" in _labels(_rows())
    full_attrs_registry._clear()


def test_flag_on_drops_the_rule_hidden_row(flag):
    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    labels = _labels(_rows({"operationModeType_astro": "defaultinattr"}))
    assert "Operation Type" not in labels and "Carry Type" in labels


@pytest.mark.parametrize("source", ["user", "hint"])
def test_the_customers_own_value_stays(flag, source):
    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    assert "Operation Type" in _labels(_rows({"operationModeType_astro": source}))


def test_a_what_if_loop_does_not_replace_the_real_loops_facts(flag):
    """The country-availability check and the validation harness run loops on a hypothetical state for the same
    catalog (all aSTRO25 products share one prefix); before or after the real loop they record nothing."""
    with full_attrs_registry.what_if_loop():
        full_attrs_registry.remember_rule_hidden(1267, "astro", {"beltClipType_astro"})
        full_attrs_registry.remember_full_attrs(1267, "astro", ["what-if"])
    assert full_attrs_registry.rule_hidden(1267, "astro") is None
    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    full_attrs_registry.remember_full_attrs(1267, "astro", ["real"])
    with full_attrs_registry.what_if_loop():
        full_attrs_registry.remember_rule_hidden(1267, "astro", {"beltClipType_astro"})
        full_attrs_registry.remember_full_attrs(1267, "astro", ["what-if"])
    assert full_attrs_registry.rule_hidden(1267, "astro") == frozenset({"operationModeType_astro"})
    assert full_attrs_registry.full_attrs(1267, "astro") == ["real"]
    labels = _labels(_rows({"operationModeType_astro": "defaultinattr"}))
    assert "Operation Type" not in labels and "Carry Type" in labels


def test_country_availability_check_runs_its_loop_as_a_what_if(flag):
    from aryx.api import ask_turn_country_available_for as mod

    seen = []

    class Engine:
        def load_product_config(self, *a):
            return [SimpleNamespace(catalog_prefix="astro", variable_name="ultimateDestinationCountry")], "APX N30"

        def _is_country_anchor_var(self, vn):
            return True

        def load_hiding_rules(self, *a):
            return []

        def load_recommendation_and_constraint_rules(self, *a):
            return [], []

        def build_bml_evaluator(self, *a):
            return None

        def _load_layout_full_order(self, *a):
            return None

        def load_layout_display_order(self, *a):
            return None

        def evaluate_rules_loop(self, *a, **k):
            full_attrs_registry.remember_rule_hidden(1267, "astro", {"beltClipType_astro"})
            seen.append(True)
            return [], {}, {}, {}

        def check_country_availability(self, *a, **k):
            return True

    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    from unittest.mock import patch
    with patch("aryx.api.ask_api._cpq_engine", Engine()):
        assert mod._country_available_for(None, 1267, "APX N30", "United States") is True
    assert seen and full_attrs_registry.rule_hidden(1267, "astro") == frozenset({"operationModeType_astro"})


def test_no_loop_for_the_catalog_drops_nothing(flag):
    full_attrs_registry.remember_rule_hidden(1267, "other", {"operationModeType_astro"})
    assert "Operation Type" in _labels(_rows())


def test_loop_records_rule_hidden_but_not_catalog_hidden(flag):
    loop_input = [_attr(1, "operationModeType_astro", "Operation Type"), _attr(2, "beltClipType_astro", "Carry Type"),
                  _attr(3, "modelSelectionbaseModel_astro", "Base Model", hidden=True)]
    rules_loop._remember_rule_hidden(loop_input, [loop_input[1]], 1267, "astro")
    assert full_attrs_registry.rule_hidden(1267, "astro") == frozenset({"operationModeType_astro"})


def test_loop_records_nothing_with_the_flag_off():
    full_attrs_registry._clear()
    rules_loop._remember_rule_hidden([SimpleNamespace(variable_name="x", hidden=False)], [], 1267, "astro")
    assert full_attrs_registry.rule_hidden(1267, "astro") is None
