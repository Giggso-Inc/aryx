"""Plan F14 (flag ``cpq_find_function_enabled``): Tier-1 understands BML
``find(<attr|literal>, "<text>") <op> <number>`` and sequential / nested
if-with-literal-return value scripts. Synthetic variable names only.
Flag off must leave behaviour unchanged (script stays unparsed).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from aryx.cpq.bml.bml_tier1 import evaluate_hide_tier1, evaluate_tier1


@contextmanager
def _flag(on: bool, nested: bool = False):
    """F14 on/off; `nested` is cpq_bml_nested_if_enabled (off here so 'F14 off'
    still means the pre-F14 behaviour, the meaning these tests assert)."""
    m = MagicMock()
    m.return_value.cpq_find_function_enabled = on
    m.return_value.cpq_bml_nested_if_enabled = nested
    with patch("aryx.cpq.bml.bml_find.get_settings", m), \
            patch("aryx.cpq.bml.bml_branches.get_settings", m):
        yield


VALUE_SCRIPT = (
    'if(zoneVar=="NA"){ return "NO"; }\n'
    'if(find(kindVar,"ALPHA") > -1){ return "NO"; } else { return "YES"; }'
)


def test_value_script_region_branch():
    with _flag(True):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "NA", "kindVar": "BETA"}) == (["NO"], False)


def test_value_script_find_contains():
    with _flag(True):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "EU", "kindVar": "X-ALPHA-1"}) == (["NO"], False)


def test_value_script_find_not_contains_falls_to_else():
    with _flag(True):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "EU", "kindVar": "GAMMA"}) == (["YES"], False)


def test_first_if_true_short_circuits_missing_second_var():
    with _flag(True):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "NA"}) == (["NO"], False)


def test_missing_variable_is_blocked_never_guessed():
    with _flag(True):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "EU"}) == (None, True)
        assert evaluate_tier1(VALUE_SCRIPT, {}) == (None, True)


def test_flag_off_value_script_not_parsed():
    with _flag(False):
        assert evaluate_tier1(VALUE_SCRIPT, {"zoneVar": "EU", "kindVar": "GAMMA"}) == (None, False)


def _hide(script: str, variables: dict[str, str]):
    with _flag(True):
        return evaluate_hide_tier1(script, variables)


def test_find_operators():
    s = 'if(find(v,"ab") %s){ return true; } else { return false; }'
    assert _hide(s % "> -1", {"v": "xxabxx"}) == (True, False)
    assert _hide(s % "> -1", {"v": "xxx"}) == (False, False)
    assert _hide(s % "== -1", {"v": "xxx"}) == (True, False)
    assert _hide(s % "== -1", {"v": "ab"}) == (False, False)
    assert _hide(s % "< 0", {"v": "xxx"}) == (True, False)
    assert _hide(s % ">= 0", {"v": "ab"}) == (True, False)
    assert _hide(s % "<> -1", {"v": "ab"}) == (True, False)
    assert _hide(s % "> 0", {"v": "ab"}) == (False, False)  # index 0, not > 0
    assert _hide(s % "> 0", {"v": "xab"}) == (True, False)


def test_find_is_case_sensitive_like_bml():
    s = 'if(find(v,"AB") > -1){ return true; } else { return false; }'
    assert _hide(s, {"v": "ab"}) == (False, False)


def test_find_with_literal_haystack_needs_no_variable():
    s = 'if(find("hello world","wor") > -1){ return true; } else { return false; }'
    assert _hide(s, {}) == (True, False)


def test_find_in_and_or_chains():
    s = 'if(find(a,"x") > -1 AND b=="Y"){ return true; } else { return false; }'
    assert _hide(s, {"a": "x", "b": "Y"}) == (True, False)
    assert _hide(s, {"a": "q", "b": "Y"}) == (False, False)
    assert _hide(s, {"a": "q"}) == (False, False)  # AND short-circuits on known False
    assert _hide(s, {"a": "x"}) == (None, True)
    mixed = 'if((find(a,"x") > -1 OR b=="Y") AND c=="Z"){ return true; } else { return false; }'
    assert _hide(mixed, {"a": "x", "b": "N", "c": "Z"}) == (True, False)
    assert _hide(mixed, {"a": "q", "b": "N", "c": "Z"}) == (False, False)
    assert _hide(mixed, {"a": "x", "b": "N"}) == (None, True)


def test_nested_ifs_with_literal_returns():
    s = ('if(zoneVar=="NA"){ if(find(kindVar,"ALPHA") > -1){ return "A"; } else { return "B"; } }'
         ' else { return "C"; }')
    with _flag(True):
        assert evaluate_tier1(s, {"zoneVar": "NA", "kindVar": "ALPHA"}) == (["A"], False)
        assert evaluate_tier1(s, {"zoneVar": "NA", "kindVar": "Z"}) == (["B"], False)
        assert evaluate_tier1(s, {"zoneVar": "EU"}) == (["C"], False)
        assert evaluate_tier1(s, {"zoneVar": "NA"}) == (None, True)
    with _flag(False):
        assert evaluate_tier1(s, {"zoneVar": "EU"}) == (None, False)
    # Nesting on its own (cpq_bml_nested_if_enabled, 2026-10-07): the chain is
    # walked, but the nested find() clause still needs F14.
    with _flag(False, nested=True):
        assert evaluate_tier1(s, {"zoneVar": "EU"}) == (["C"], False)
        assert evaluate_tier1(s, {"zoneVar": "NA", "kindVar": "ALPHA"}) == (None, False)


def test_sequential_ifs_with_trailing_literal_return():
    s = 'if(a=="1"){ return "ONE"; } if(a=="2"){ return "TWO"; } return "OTHER";'
    with _flag(True):
        assert evaluate_tier1(s, {"a": "2"}) == (["TWO"], False)
        assert evaluate_tier1(s, {"a": "9"}) == (["OTHER"], False)
        assert evaluate_tier1(s, {}) == (None, True)


def test_sequential_ifs_not_chained_when_body_has_side_effects():
    s = 'if(a=="1"){ r = "x"; } if(a=="2"){ return "TWO"; } else { return "Z"; }'
    with _flag(True):
        assert evaluate_tier1(s, {"a": "5"}) == (None, False)


def test_empty_trailing_return_still_means_no_value():
    s = 'if(a=="1"){ return "ONE"; } return "";'
    with _flag(True):
        assert evaluate_tier1(s, {"a": "2"}) == (None, False)


def test_existing_idioms_unchanged_with_flag_on():
    s = 'if(a=="1" OR b<>"2"){ return false; } else { return true; }'
    with _flag(True):
        assert evaluate_hide_tier1(s, {"a": "1", "b": "2"}) == (False, False)
        assert evaluate_hide_tier1(s, {"a": "0", "b": "2"}) == (True, False)
