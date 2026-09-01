"""Regression coverage for referenced_variables() (bml.py) -- the
function that scopes allowed_values_for_script's cache key by which
variables a script actually compares.

Live-verified regression (PR #117 review): the first fix for missing
bare-boolean support put a trailing `\\b` after the WHOLE alternation,
including the quoted-string branch. A word boundary can never match
right after a closing `"`, so the quoted-string case -- the far more
common one -- silently matched nothing at all, which would have
reintroduced the exact "stale cached result reused forever" bug this
function exists to prevent, just for quoted-string scripts instead of
boolean ones.
"""
from __future__ import annotations

from aryx.cpq.bml import referenced_variables


def test_quoted_string_comparison_detected():
    assert referenced_variables('archeType_viSoln=="CAPEX PURCHASE"') == {"archeType_viSoln"}


def test_quoted_string_comparison_with_spacing_detected():
    assert referenced_variables('if (hWVersion_astro == "NEXT ENHANCED") { }') == {"hWVersion_astro"}


def test_bare_true_literal_detected():
    assert referenced_variables("if (spareBattery_viSoln == true) { }") == {"spareBattery_viSoln"}


def test_bare_false_literal_detected():
    assert referenced_variables("if (x == false) { }") == {"x"}


def test_multiple_comparisons_all_detected():
    script = 'if (a=="X" AND b == true) { } elif (c <> "Y") { }'
    assert referenced_variables(script) == {"a", "b", "c"}


def test_not_equal_and_diamond_operators_detected():
    assert referenced_variables('x <> "A"') == {"x"}
    assert referenced_variables('y != "B"') == {"y"}


def test_no_comparisons_returns_empty_set():
    assert referenced_variables("return \"\";") == set()
