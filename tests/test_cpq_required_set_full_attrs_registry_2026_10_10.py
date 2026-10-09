"""The required set reads the full attribute list in every caller, not only inside evaluate_rules_loop.

ws 1267, APX 3000 / APX 900: with cpq_required_set_rules_read_all_attrs_enabled on, the Encryption Type rule fired in
the loop (`rule_inputs_from_all_attrs: true`, kept) and was dropped by the post-loop auto_fill, which does not share the
loop's turn cache (`false`, attr_count 34). The loop now also records its list for the request.
"""
from __future__ import annotations

import contextvars
from types import SimpleNamespace

import pytest

from aryx.cpq.auto_fill import auto_fill_setup
from aryx.cpq.rules_loop import full_attrs_registry


@pytest.fixture(autouse=True)
def _clean():
    full_attrs_registry._clear()
    auto_fill_setup._ALL_ATTRS_MISSING_WARNED.clear()
    yield
    full_attrs_registry._clear()


ON = SimpleNamespace(cpq_required_set_rules_read_all_attrs_enabled=True)
OFF = SimpleNamespace(cpq_required_set_rules_read_all_attrs_enabled=False)
FULL = ["a", "b", "c"]


def test_flag_off_returns_none():
    full_attrs_registry.remember_full_attrs(1267, "astro", FULL)
    assert auto_fill_setup._rule_input_attrs(OFF, 1267, "astro", {}) is None


def test_turn_cache_wins():
    cache = {("_all_attrs", 1267, "astro"): ["x"]}
    full_attrs_registry.remember_full_attrs(1267, "astro", FULL)
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "astro", cache) == ["x"]


def test_caller_with_its_own_cache_gets_the_loops_list():
    full_attrs_registry.remember_full_attrs(1267, "astro", FULL)
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "astro", {}) == FULL
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "astro", None) == FULL


def test_other_catalog_is_not_mixed_in():
    full_attrs_registry.remember_full_attrs(1267, "astro", FULL)
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "other", {}) is None
    assert auto_fill_setup._rule_input_attrs(ON, 1150, "astro", {}) is None


def test_missing_list_warns_once(monkeypatch):
    calls = []
    monkeypatch.setattr(auto_fill_setup, "raven_log", lambda *a, **k: calls.append(a))
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "astro", {}) is None
    assert auto_fill_setup._rule_input_attrs(ON, 1267, "astro", {}) is None
    assert len(calls) == 1 and "all_attrs_missing" in calls[0][2]


def test_another_request_never_sees_this_requests_list():
    full_attrs_registry.remember_full_attrs(1267, "astro", FULL)
    other_request = contextvars.Context()          # a fresh request context, as a concurrent request has
    assert other_request.run(full_attrs_registry.full_attrs, 1267, "astro") is None
    assert full_attrs_registry.full_attrs(1267, "astro") == FULL


def test_reader_cannot_change_the_stored_list():
    source = list(FULL)
    full_attrs_registry.remember_full_attrs(1267, "astro", source)
    full_attrs_registry.full_attrs(1267, "astro").append("z")
    source.append("y")
    assert full_attrs_registry.full_attrs(1267, "astro") == FULL


def test_empty_list_is_not_stored():
    full_attrs_registry.remember_full_attrs(1267, "astro", [])
    assert full_attrs_registry.full_attrs(1267, "astro") is None
