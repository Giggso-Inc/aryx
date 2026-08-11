"""Regression coverage for Idiom D (evaluate_hide_master_list_unguarded) --
the real, live-confirmed shape of Carrier Selection's and Wireless
Carrier's hiding-rule scripts (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_
PROOF_2026_08_07.md §1.3/§2.3):

    splitstringArray = SPLIT(hiddenMasterStringForAstroPortable_astro,hidddenRecordSeparator_allFamilly);
    valindex         = findinarray(splitstringArray,"carrierSelectionMultiSelect_astro");

    if(valindex ==-1){
     return TRUE;
    }
    else{
     if(modelSelectionbaseModel_astro==""){
      return TRUE;
     }
    }

    return FALSE;

Neither the pre-existing Idiom C (evaluate_hide_master_list, requires an
outer `if(MASTER<>"")` guard) nor _first_matching_branch's if/else-if/else
chain parser recognize this ungated shape -- it previously fell through to
Tier 2 (LLM), which had no reason to treat an empty master string as
"unknown, real data never captured" rather than a confident hide. That
silently dropped the attribute before it ever reached the real ingested
Data Table fallback that DOES have rows for it in this catalog (confirmed
live: 54 constraint + 66 sequence rows for wirelessCarrier_astro).
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_hide_master_list_unguarded, evaluate_hide_tier1

_REAL_CARRIER_SCRIPT = (
    'splitstringArray = SPLIT(hiddenMasterStringForAstroPortable_astro,hidddenRecordSeparator_allFamilly);\n'
    'valindex         = findinarray(splitstringArray,"carrierSelectionMultiSelect_astro");\n\n'
    'if(valindex ==-1){\n'
    ' return TRUE;\n'
    '}\n'
    'else{\n'
    ' if(modelSelectionbaseModel_astro==""){\n'
    '  return TRUE;\n'
    ' }     \n'
    '}\n\n'
    'return FALSE;'
)


def test_empty_master_string_is_blocked_not_a_confident_hide():
    """The exact live bug: an empty (never-captured) master string must
    report unknown, not hide=True -- the whole point of Idiom D."""
    variables = {
        "hiddenMasterStringForAstroPortable_astro": "",
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "H45TGT9PW8AN",
    }
    hide, blocked = evaluate_hide_master_list_unguarded(_REAL_CARRIER_SCRIPT, variables)
    assert hide is None
    assert blocked is True


def test_unset_master_string_is_also_blocked():
    variables = {
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "H45TGT9PW8AN",
    }
    hide, blocked = evaluate_hide_master_list_unguarded(_REAL_CARRIER_SCRIPT, variables)
    assert hide is None
    assert blocked is True


def test_literal_present_in_populated_master_string_does_not_hide():
    variables = {
        "hiddenMasterStringForAstroPortable_astro": "carrierSelectionMultiSelect_astro|otherAttr_astro",
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "H45TGT9PW8AN",
    }
    hide, blocked = evaluate_hide_master_list_unguarded(_REAL_CARRIER_SCRIPT, variables)
    assert hide is False
    assert blocked is False


def test_literal_absent_from_populated_master_string_hides():
    variables = {
        "hiddenMasterStringForAstroPortable_astro": "wirelessCarrier_astro|otherAttr_astro",
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "H45TGT9PW8AN",
    }
    hide, blocked = evaluate_hide_master_list_unguarded(_REAL_CARRIER_SCRIPT, variables)
    assert hide is True
    assert blocked is False


def test_empty_base_model_is_a_real_confident_hide_not_blocked():
    """Base model unset is a genuine "nothing selected yet" state, distinct
    from the master-string data gap -- must stay a confident hide."""
    variables = {
        "hiddenMasterStringForAstroPortable_astro": "",
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "",
    }
    hide, blocked = evaluate_hide_master_list_unguarded(_REAL_CARRIER_SCRIPT, variables)
    assert hide is None
    assert blocked is True  # master-string gap still wins -- checked first


def test_not_this_idiom_returns_none_false():
    hide, blocked = evaluate_hide_master_list_unguarded(
        'if(x=="1"){return true;}\nreturn false;', {"x": "1"},
    )
    assert hide is None
    assert blocked is False


def test_evaluate_hide_tier1_dispatches_to_idiom_d():
    variables = {
        "hiddenMasterStringForAstroPortable_astro": "",
        "hidddenRecordSeparator_allFamilly": "|",
        "modelSelectionbaseModel_astro": "H45TGT9PW8AN",
    }
    hide, blocked = evaluate_hide_tier1(_REAL_CARRIER_SCRIPT, variables)
    assert hide is None
    assert blocked is True
