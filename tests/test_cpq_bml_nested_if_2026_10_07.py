"""Tier-1 BML walks a nested if/else chain without the F14 flag.

Live case (2026-10-07, ws 1267, catalog Astro25Configdata): the hiding rule
"Hide HW Version unless APX Next NA or APX Next fed model" nests its region
check inside the model check. Tier 1 reported the whole script unparseable,
the hide outcome stayed unknown, so Hardware Version (a forced-ask anchor)
stayed visible and was asked for an APX 900 quote.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.bml.bml_tier1 import evaluate_hide_tier1

# The real script body (condition_function_id 14751487256 / 14751487258).
HW_VERSION_HIDE = '''if( (_bm_model_variable_name=="aPXNext") ){
	if (modelSelectionRegion_astro=="NA"){
		return false;
		}
		else{
		return true;
		}
}
else{
return true;
}'''


@contextmanager
def _settings(nested: bool, find: bool = False):
    """Patch the two flags read by the Tier-1 parser."""
    m = MagicMock()
    m.return_value.cpq_bml_nested_if_enabled = nested
    m.return_value.cpq_find_function_enabled = find
    with patch("aryx.cpq.bml.bml_find.get_settings", m), \
            patch("aryx.cpq.bml.bml_branches.get_settings", m):
        yield


@pytest.mark.parametrize("variables,expected", [
    ({"_bm_model_variable_name": "aPX900"}, (True, False)),                  # other model: hide
    ({"_bm_model_variable_name": "aPXNext",
      "modelSelectionRegion_astro": "NA"}, (False, False)),                  # APX Next NA: show
    ({"_bm_model_variable_name": "aPXNext",
      "modelSelectionRegion_astro": "EMEA"}, (True, False)),                 # APX Next intl: hide
    ({"_bm_model_variable_name": "aPXNext"}, (None, True)),                  # region unknown: blocked
    ({}, (None, True)),                                                      # model unknown: blocked
])
def test_real_hw_version_script_resolves_with_nesting_on(variables, expected):
    with _settings(nested=True):
        assert evaluate_hide_tier1(HW_VERSION_HIDE, variables) == expected


def test_kill_switch_restores_unparseable():
    with _settings(nested=False):
        assert evaluate_hide_tier1(HW_VERSION_HIDE, {"_bm_model_variable_name": "aPX900"}) == (None, False)


def test_f14_alone_still_enables_nesting():
    with _settings(nested=False, find=True):
        assert evaluate_hide_tier1(HW_VERSION_HIDE, {"_bm_model_variable_name": "aPX900"}) == (True, False)


def test_nested_chain_in_else_branch():
    s = ('if(a=="1"){ return true; } else { if(b=="X"){ return false; } else { return true; } }')
    with _settings(nested=True):
        assert evaluate_hide_tier1(s, {"a": "1"}) == (True, False)
        assert evaluate_hide_tier1(s, {"a": "2", "b": "X"}) == (False, False)
        assert evaluate_hide_tier1(s, {"a": "2", "b": "Y"}) == (True, False)
        assert evaluate_hide_tier1(s, {"a": "2"}) == (None, True)


def test_body_with_if_not_at_start_is_still_unsupported():
    """Only a body that IS an if-chain is walked; code before an inner if is not."""
    s = 'if(a=="1"){ x = "y"; if(b=="2"){ return true; } } else { return false; }'
    with _settings(nested=True):
        assert evaluate_hide_tier1(s, {"a": "1", "b": "2"}) == (None, False)


def test_flat_scripts_unchanged():
    s = 'if(a=="1"){ return true; } else { return false; }'
    for nested in (True, False):
        with _settings(nested=nested):
            assert evaluate_hide_tier1(s, {"a": "1"}) == (True, False)
            assert evaluate_hide_tier1(s, {"a": "2"}) == (False, False)
            assert evaluate_hide_tier1(s, {}) == (None, True)


def test_default_settings_enable_nesting():
    from aryx.config import get_settings
    assert get_settings().cpq_bml_nested_if_enabled is True
