"""BML allows `return"text"` with no space after `return`. With the value-script flag on
(`cpq_find_function_enabled`) Tier 1 accepts it; with the flag off behaviour is unchanged.
Synthetic variable names and values only.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.bml import bml_find, bml_tier1

NO_SPACE = '''
if(regionVar =="NA"){
 return"VALUE ONE";
}
else{
 return"";
}
'''
WITH_SPACE = NO_SPACE.replace('return"', 'return "')


def _run(script, on, region):
    cfg = MagicMock()
    cfg.return_value.cpq_find_function_enabled = on
    with patch.object(bml_find, "get_settings", cfg):
        return bml_tier1.evaluate_tier1(script, {"regionVar": region})


def test_return_without_a_space_resolves_only_when_the_flag_is_on():
    assert _run(NO_SPACE, False, "NA") == (None, False)                 # old behaviour: unknown
    assert _run(NO_SPACE, True, "NA") == (["VALUE ONE"], False)


def test_the_spaced_form_is_unchanged_by_the_flag():
    assert _run(WITH_SPACE, False, "NA") == (["VALUE ONE"], False)
    assert _run(WITH_SPACE, True, "NA") == (["VALUE ONE"], False)


def test_a_variable_that_merely_starts_with_return_is_not_mistaken_for_a_return():
    script = 'returnVal = "X"; if(regionVar =="NA"){ returnVal = "VALUE ONE"; } return returnVal;'
    assert _run(script, True, "NA")[0] in (None, ["VALUE ONE"])           # never a wrong literal
    assert _run(script, True, "NA")[0] != ["X"]
