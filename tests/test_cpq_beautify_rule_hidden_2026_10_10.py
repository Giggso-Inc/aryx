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


def test_the_customers_own_answer_stays(flag):
    full_attrs_registry.remember_rule_hidden(1267, "astro", {"operationModeType_astro"})
    assert "Operation Type" in _labels(_rows({"operationModeType_astro": "user"}))


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
