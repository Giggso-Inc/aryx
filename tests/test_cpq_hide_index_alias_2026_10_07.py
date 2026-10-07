"""ws 1267 (2026-10-07): 3,225 hide scripts assign `lindex = findinarray(...)` but test `valindex ==-1`, so the strict
master-list idioms never matched and every such rule was left undecided (its target stayed visible and was asked).
Behind cpq_hide_index_alias_enabled the unassigned tested name stands for the findinarray result. Flag off: unchanged."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.bml.bml_hide_idioms import evaluate_hide_master_list, evaluate_hide_master_list_unguarded
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from aryx.cpq.state import ConfigAttr, HidingRule, RecommendationRule

MASTER, SEP, BASE_VAR, LITERAL = "masterVar", "sepVar", "baseVar", "widgetAttr"
D_TEMPLATE = (
    '/** header **/\n'
    'arr = SPLIT(masterVar,sepVar);\n'
    '{assigned} = findinarray(arr,"widgetAttr");\n\n'
    'if({tested} ==-1){\n return TRUE;\n}\nelse{\n if(baseVar==""){\n  return TRUE;\n }\n}\n\nreturn FALSE;'
)
C_TEMPLATE = (
    'if(masterVar<>""){ arr = SPLIT(masterVar,sepVar); {assigned} = findinarray(arr,"widgetAttr");\n'
    'if ({tested} ==-1){ return TRUE; } }\nreturn FALSE;'
)


def _d(assigned="lindex", tested="valindex"):
    return D_TEMPLATE.replace("{assigned}", assigned).replace("{tested}", tested)


def _c(assigned="lindex", tested="valindex"):
    return C_TEMPLATE.replace("{assigned}", assigned).replace("{tested}", tested)


def _vars(master: str, base: str = "B1") -> dict[str, str]:
    return {MASTER: master, SEP: "@@", BASE_VAR: base}


PRESENT, ABSENT = "a@@widgetAttr@@b@@", "a@@b@@"


@pytest.mark.parametrize("master,expected", [(PRESENT, False), (ABSENT, True), ("", True)])
def test_idiom_d_with_an_unassigned_tested_index_is_decided_when_opted_in(master, expected):
    assert evaluate_hide_master_list_unguarded(_d(), _vars(master), True, alias_unassigned_index=True) == (expected, False)


def test_idiom_d_is_undecided_without_the_opt_in():
    for master in (PRESENT, ABSENT, ""):
        assert evaluate_hide_master_list_unguarded(_d(), _vars(master), True) == (None, False)


@pytest.mark.parametrize("master,expected", [(PRESENT, False), (ABSENT, True), ("", False)])
def test_idiom_c_with_an_unassigned_tested_index_is_decided_when_opted_in(master, expected):
    assert evaluate_hide_master_list(_c(), _vars(master), alias_unassigned_index=True) == (expected, False)


def test_idiom_c_is_undecided_without_the_opt_in():
    assert evaluate_hide_master_list(_c(), _vars(ABSENT)) == (None, False)


def test_a_matching_script_behaves_the_same_with_and_without_the_opt_in():
    for master in (PRESENT, ABSENT, ""):
        strict = evaluate_hide_master_list_unguarded(_d("idx", "idx"), _vars(master), True)
        assert strict == evaluate_hide_master_list_unguarded(_d("idx", "idx"), _vars(master), True, True)
        assert strict[0] is not None


def test_a_tested_name_that_is_a_real_variable_is_never_aliased():
    variables = {**_vars(ABSENT), "valindex": "3"}                  # valindex is a real, known variable here
    assert evaluate_hide_master_list_unguarded(_d(), variables, True, alias_unassigned_index=True) == (None, False)


def test_a_script_that_is_not_the_idiom_is_untouched():
    other = 'return someVar == "x";'
    assert evaluate_hide_master_list_unguarded(other, _vars(ABSENT), True, alias_unassigned_index=True) == (None, False)
    assert evaluate_hide_master_list(other, _vars(ABSENT), alias_unassigned_index=True) == (None, False)


# --- end to end through apply_hiding_rules (F9 on) ---------------------------------------------------------------
WRITER_SCRIPT = (
    'cpqModel = modelVar;\n'
    'q = BMQL("SELECT distinct AttrName FROM $tblVar WHERE CPQModel=$cpqModel and BaseModel IN ($baseVar)");\n'
    'for r in q { out = out + r.AttrName + sepVar; }\nreturn out;'
)
ROWS = [{"CPQModel": "M1", "BaseModel": "B1", "AttrName": "widgetAttr", "Seq": "1"},
        {"CPQModel": "M1", "BaseModel": "B2", "AttrName": "gadgetAttr", "Seq": "1"}]


def _attr(eid: int, vn: str, default: str = "") -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False,
                      default_value=default, options=[], source_id=eid)


def _attrs() -> list[ConfigAttr]:
    return [_attr(1, "widgetAttr"), _attr(2, "countryVar"), _attr(3, MASTER), _attr(4, BASE_VAR),
            _attr(5, SEP, "@@"), _attr(6, "modelVar"), _attr(7, "tblVar", "seqTable")]


def _hide_rule() -> HidingRule:
    rule = HidingRule(rule_name="h", condition_attr_id=0, condition_value="", target_attr_id=1, script=_d())
    rule.master_writers = [RecommendationRule(
        rule_name="w", condition_attr_id=2, condition_value="", target_attr_id=3,
        script=WRITER_SCRIPT, conditions=[(2, "", "3")])]
    return rule


@contextmanager
def _flags(alias: bool):
    settings = MagicMock()
    settings.return_value.cpq_master_string_hide_enabled = True
    settings.return_value.cpq_hide_index_alias_enabled = alias
    with patch("aryx.cpq.hiding_rules.master_writers.get_settings", settings), \
            patch("aryx.cpq.data_table.data_table_loader._load_all_tables", return_value=([], ROWS, [], [], [])):
        yield


def _hidden(filled: dict[str, str]) -> set[str]:
    return apply_hiding_rules(_attrs(), filled, [_hide_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
                              workspace_id=1)[2]


def test_end_to_end_the_attribute_absent_from_the_computed_master_is_hidden_when_opted_in():
    filled = {"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}     # B2's master lacks widgetAttr
    with _flags(True):
        assert _hidden(filled) == {"widgetAttr"}


def test_end_to_end_the_attribute_present_in_the_computed_master_is_shown_when_opted_in():
    with _flags(True):
        assert _hidden({"modelVar": "M1", "baseVar": "B1", "countryVar": "ZZ"}) == set()


def test_end_to_end_flag_off_keeps_the_old_undecided_behaviour():
    with _flags(False):
        assert _hidden({"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}) == set()
