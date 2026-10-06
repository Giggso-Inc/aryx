"""Plan F5 consumer: a recommendation script that only looks the RTTE/non-RTTE/TA
flag up in the reference table is answered from the ingested table. Flag
`cpq_country_region_table_enabled`; synthetic table, attribute and label names.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.data_table import data_table_geo as geo
from aryx.cpq.recommendation_and_constraint_rules import rule_condition as rc
from aryx.cpq.recommendation_and_constraint_rules import table_lookup_script as tls
from aryx.cpq.state import RecommendationRule

SCRIPT = '''
/* sets the flag from the destination country */
returnVal = "";
rec = bmql("select RTTE,nonRTTE,TA from someRefTable where countryCode=$countryVar");
for records in rec{
    if(upper(get(records,"RTTE")) =="YES"){
        returnVal ="LABEL ONE";
    }
    elif(upper(get(records,"nonRTTE")) =="YES"){
         returnVal ="LABEL TWO";
    }
    elif(upper(get(records,"TA")) =="YES"){
         returnVal ="LABEL THREE";
    }
}
return returnVal;
'''


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


ROWS = [
    {"countryCode": "AA", "RTTE": "Yes", "nonRTTE": "", "TA": ""},
    {"countryCode": "BB", "RTTE": "", "nonRTTE": "Yes", "TA": ""},
    {"countryCode": "CC", "RTTE": "", "nonRTTE": "", "TA": "Yes"},
    {"countryCode": "DD", "RTTE": "", "nonRTTE": "", "TA": ""},
]


def test_the_script_shape_is_recognised_with_its_key_attribute_and_labels():
    var, labels = tls.parse_flag_lookup(SCRIPT)
    assert var == "countryVar"
    assert labels == {"RTTE": "LABEL ONE", "nonRTTE": "LABEL TWO", "TA": "LABEL THREE"}


def test_other_scripts_are_not_recognised():
    assert tls.parse_flag_lookup(None) is None
    assert tls.parse_flag_lookup('x = bmql("select a,b from t where k=$v"); return "x";') is None
    assert tls.parse_flag_lookup(SCRIPT.replace("RTTE,nonRTTE,TA", "RTTE,nonRTTE")) is None
    assert tls.parse_flag_lookup('// ' + SCRIPT.replace("\n", "\n// ")) is None            # commented out


def _lookup(flag, filled):
    with patch.object(tls, "get_settings", _cfg(cpq_country_region_table_enabled=flag)), \
            patch.object(geo, "_cached_shape_scan", return_value=ROWS):
        return tls.lookup_script_value(SCRIPT, filled, 1)


def test_the_value_comes_from_the_table_using_the_scripts_own_labels():
    assert _lookup(True, {"countryVar": "AA"}) == "LABEL ONE"
    assert _lookup(True, {"countryVar": "bb"}) == "LABEL TWO"
    assert _lookup(True, {"countryVar": "CC"}) == "LABEL THREE"
    assert _lookup(True, {"countryVar": "DD"}) is None          # row without a flag
    assert _lookup(True, {"countryVar": "ZZ"}) is None          # no row
    assert _lookup(True, {}) is None                            # key attribute unfilled


def test_flag_off_or_no_workspace_gives_none():
    assert _lookup(False, {"countryVar": "AA"}) is None
    with patch.object(tls, "get_settings", _cfg(cpq_country_region_table_enabled=True)):
        assert tls.lookup_script_value(SCRIPT, {"countryVar": "AA"}, None) is None


def test_a_recommendation_rule_with_that_script_resolves_through_the_table_without_an_evaluator():
    rule = RecommendationRule(rule_name="r", condition_attr_id=0, condition_value="", target_attr_id=7, script=SCRIPT)
    with patch.object(tls, "get_settings", _cfg(cpq_country_region_table_enabled=True)), \
            patch.object(geo, "_cached_shape_scan", return_value=ROWS):
        assert rc.resolve_recommended_value(rule, {"countryVar": "BB"}, {}, None, 1, "", None) == "LABEL TWO"
        assert rc.resolve_recommended_value(rule, {"countryVar": "DD"}, {}, None, 1, "", None) is None     # unknown: never guess
    with patch.object(tls, "get_settings", _cfg(cpq_country_region_table_enabled=False)):
        assert rc.resolve_recommended_value(rule, {"countryVar": "BB"}, {}, None, 1, "", None) is None      # old behaviour
