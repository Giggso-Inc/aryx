"""Tier 1 reads an `elif(` chain whose later conditions nest AND/OR groups. Flag
`cpq_find_function_enabled`; synthetic variable and value names."""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.bml import bml_branches as bb
from aryx.cpq.bml import bml_tier1 as t1

SCRIPT = '''
if(zone =="N"){
 return"ONE";
}
elif(((zone=="A") OR (zone=="B")) AND (flag=="NO")){
 return"TWO";
}
elif(((zone=="A") OR (zone=="B")) AND (flag=="YES")){
 return"THREE";
}
else{
 return"";
}
'''


def _run(enabled, zone, flag):
    with patch.object(bb, "find_enabled", lambda: enabled):
        return t1.evaluate_tier1(SCRIPT, {"zone": zone, "flag": flag})[0]


def test_each_branch_of_the_chain_resolves_when_the_flag_is_on():
    assert _run(True, "N", "") == ["ONE"]
    assert _run(True, "B", "NO") == ["TWO"]
    assert _run(True, "A", "YES") == ["THREE"]
    assert _run(True, "C", "YES") == []


def test_flag_off_keeps_the_old_result():
    assert _run(False, "B", "NO") is None


def test_an_undecided_variable_stays_unknown():
    with patch.object(bb, "find_enabled", lambda: True):
        assert t1.evaluate_tier1(SCRIPT, {"zone": "B"})[0] is None


ASSIGN_SCRIPT = '''
retVal = FALSE;
rows = BMQL("select g from t where k=$who");
for record in rows{
    grp = get(record,"g");
}
if ((who == "X1") AND ((kind=="A") OR (kind=="B"))){
    retVal = FALSE;
}
elif ((zone == "BR")){
    retVal = FALSE;
}
else{
    retVal = TRUE;
}
return retVal;
'''


def _cond(enabled, **v):
    with patch.object(bb, "find_enabled", lambda: enabled):
        return t1.evaluate_hide_tier1(ASSIGN_SCRIPT, v)


def test_condition_script_that_assigns_a_boolean_and_returns_it_resolves():
    assert _cond(True, who="", kind="", zone="US") == (True, False)
    assert _cond(True, who="", kind="", zone="BR") == (False, False)
    assert _cond(True, who="X1", kind="B", zone="US") == (False, False)


def test_boolean_assignment_idiom_is_off_without_the_flag():
    assert _cond(False, who="", kind="", zone="US") == (None, False)
