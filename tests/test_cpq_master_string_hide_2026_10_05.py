"""Plan F9 (flag ``cpq_master_string_hide_enabled``): hide scripts that search
a master string are evaluated with the master COMPUTED from the writer rule
(its declarative condition) + the ingested attrSequence rows. Synthetic
names only. Flag off must behave exactly as before.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from aryx.cpq.hiding_rules.master_writers import (
    annotate_hiding_rules, find_master_writers, parse_writer_query,
)
from aryx.cpq.state import ConfigAttr, HidingRule, RecommendationRule

WRITER_SCRIPT = (
    'cpqModel = modelVar;\n'
    'q = BMQL("SELECT distinct AttrName FROM $tblVar WHERE CPQModel=$cpqModel '
    'and BaseModel IN ($baseVar)");\n'
    'for r in q { out = out + r.AttrName + recSep; }\nreturn out;'
)
MULTI_COL_WRITER = (
    'q = BMQL("SELECT distinct AttrName,Seq,optionOrReqFlag FROM $tblVar '
    'WHERE CPQModel=$modelVar");'
)
HIDE_D = (
    'arr = SPLIT(masterVar,recSep);\n'
    'idx = findinarray(arr,"widgetAttr");\n'
    'if(idx ==-1){ return TRUE; } else { if(baseVar==""){ return TRUE; } }\n'
    'return FALSE;'
)
HIDE_C = (
    'if(masterVar<>""){ arr = SPLIT(masterVar,recSep); idx = findinarray(arr,"widgetAttr");\n'
    'if (idx ==-1){ return TRUE; } }\nreturn FALSE;'
)
ROWS = [
    {"CPQModel": "M1", "BaseModel": "B1", "AttrName": "widgetAttr", "Seq": "1"},
    {"CPQModel": "M1", "BaseModel": "B1", "AttrName": "otherAttr", "Seq": "2"},
    {"CPQModel": "M1", "BaseModel": "B2", "AttrName": "gadgetAttr", "Seq": "1"},
]


def _attr(eid: int, vn: str, default: str = "") -> ConfigAttr:
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False,
                      default_value=default, options=[], source_id=eid)


def _attrs() -> list[ConfigAttr]:
    return [_attr(1, "widgetAttr"), _attr(2, "countryVar"), _attr(3, "masterVar"),
            _attr(4, "baseVar"), _attr(5, "recSep", "@@@"), _attr(6, "modelVar"),
            _attr(7, "tblVar", "seqTable")]


def _writer(script: str = WRITER_SCRIPT) -> RecommendationRule:
    # target = masterVar (id 3); fires only when countryVar (id 2) is not blank
    return RecommendationRule(
        rule_name="w", condition_attr_id=2, condition_value="", target_attr_id=3,
        script=script, conditions=[(2, "", "3")])


def _hide_rule(script: str = HIDE_D, with_writers: bool = True) -> HidingRule:
    r = HidingRule(rule_name="h", condition_attr_id=0, condition_value="", target_attr_id=1, script=script)
    if with_writers:
        r.master_writers = [_writer()]
    return r


@contextmanager
def _flag(on: bool):
    m = MagicMock()
    m.return_value.cpq_master_string_hide_enabled = on
    with patch("aryx.cpq.hiding_rules.master_writers.get_settings", m), \
            patch("aryx.cpq.data_table.data_table_loader._load_all_tables",
                  return_value=([], ROWS, [], [], [])):
        yield


def _run(filled: dict[str, str], rule: HidingRule | None = None):
    _vis, _msgs, hidden = apply_hiding_rules(
        _attrs(), filled, [rule or _hide_rule()], bml_eval=BmlEvaluator({}, use_llm=False),
        workspace_id=1)
    return hidden


BASE = {"modelVar": "M1", "baseVar": "B1"}


def test_empty_master_hides_before_writer_condition_holds():
    with _flag(True):
        assert _run(dict(BASE)) == {"widgetAttr"}  # country blank -> writer silent


def test_populated_master_with_attribute_present_shows():
    with _flag(True):
        assert _run({**BASE, "countryVar": "ZZ"}) == set()


def test_populated_master_without_attribute_hides():
    with _flag(True):
        assert _run({"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}) == {"widgetAttr"}


def test_blank_base_model_hides_via_script_check():
    with _flag(True):
        assert _run({"modelVar": "M1", "countryVar": "ZZ"}) == {"widgetAttr"}


def test_guarded_idiom_keeps_its_guard_semantics_when_master_empty():
    with _flag(True):
        assert _run(dict(BASE), _hide_rule(HIDE_C)) == set()  # outer if(master<>"") false -> show
        assert _run({"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}, _hide_rule(HIDE_C)) == {"widgetAttr"}


def test_flag_off_empty_master_does_not_hide_old_path():
    with _flag(False):
        assert _run(dict(BASE)) == set()  # Idiom D: empty master is "unknown"


def test_no_writers_attached_uses_old_path():
    with _flag(True):
        assert _run(dict(BASE), _hide_rule(with_writers=False)) == set()


def test_multi_column_writer_empty_ok_but_populated_not_computed():
    rule = _hide_rule()
    rule.master_writers = [_writer(MULTI_COL_WRITER)]
    with _flag(True):
        assert _run(dict(BASE), rule) == {"widgetAttr"}  # condition False -> empty, sound
        assert _run({**BASE, "countryVar": "ZZ"}, rule) == set()  # cannot format -> old path (unknown)


def test_unresolved_model_scope_is_unknown_not_guessed():
    with _flag(True):
        assert _run({"baseVar": "B1", "countryVar": "ZZ"}) == set()


def test_writer_detection_from_script_data():
    q = parse_writer_query(WRITER_SCRIPT)
    assert q and q.columns == ("attrname",) and q.cpq_var == "cpqModel" and q.simple
    assert q.base_items == (("var", "baseVar"),)
    multi = parse_writer_query(MULTI_COL_WRITER)
    assert multi and multi.columns == ("attrname", "seq", "optionorreqflag")
    assert parse_writer_query('return "x";') is None
    other = RecommendationRule(rule_name="o", condition_attr_id=0, condition_value="",
                               target_attr_id=9, script='return "x";')
    assert len(find_master_writers([_writer(), other])) == 1


def test_annotation_only_with_flag_and_split_reader():
    plain = HidingRule(rule_name="p", condition_attr_id=0, condition_value="", target_attr_id=1,
                       script='if(a=="1"){return true;} return false;')
    reader = _hide_rule(with_writers=False)
    with _flag(True):
        assert annotate_hiding_rules([plain, reader], [_writer()]) == 1
        assert reader.master_writers and plain.master_writers is None
    reader2 = _hide_rule(with_writers=False)
    with _flag(False):
        assert annotate_hiding_rules([reader2], [_writer()]) == 0
        assert reader2.master_writers is None


def test_writer_condition_non_blank_value_and_value_match():
    rule = _hide_rule()
    rule.master_writers[0].conditions = [(2, "ZZ", "4")]  # fires only when country == ZZ
    with _flag(True):
        assert _run({**BASE, "countryVar": "QQ"}, rule) == {"widgetAttr"}  # False -> empty -> hide
        assert _run({**BASE, "countryVar": "ZZ"}, rule) == set()


def test_writer_without_any_condition_is_unknown_old_path():
    rule = _hide_rule()
    w = rule.master_writers[0]
    w.conditions, w.condition_attr_id = None, -1
    with _flag(True):
        assert _run(dict(BASE), rule) == set()
