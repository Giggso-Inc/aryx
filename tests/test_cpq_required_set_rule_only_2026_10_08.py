"""`derive_required_vns(rule_required_only=True)` takes candidates only from the rules, never from attrSequence R."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.payload_building import required_set

FCC, ENC = "requireForRadioFEDFCCTriggerSS_astro", "secureEncryptionType_astro"


def _attr(vn):
    return SimpleNamespace(variable_name=vn, hidden=False, entity_id=abs(hash(vn)) % 10_000)


def _derive(rule_only):
    attrs = [_attr(FCC), _attr(ENC)]
    engine = SimpleNamespace(load_recommendation_and_constraint_rules=lambda *a, **k: ([], []))
    settings = SimpleNamespace(cpq_series_model_narrowing_enabled=False)
    with patch.object(required_set, "get_settings", return_value=settings), \
            patch.object(required_set, "resolve_base_model_vn", return_value="modelSelectionbaseModel_astro"), \
            patch.object(required_set._engine_module, "_cpq_model_candidates", return_value=("APX900",)), \
            patch.object(required_set, "r_flagged_names", return_value={FCC}) as r_flag, \
            patch.object(required_set, "rule_required_vns", return_value={ENC}), \
            patch.object(required_set, "script_filled_quantity_vns", return_value=set()), \
            patch.object(required_set, "_visible", return_value=True), \
            patch.object(required_set, "no_legal_value", return_value=False):
        out = required_set.derive_required_vns(
            engine, attrs, {"productSelectionProduct_all": "APX 900"}, {}, {}, set(), None, 1267, "p", "", {},
            rule_required_only=rule_only)
    return out, r_flag


def test_the_full_set_holds_the_attrsequence_r_attribute_and_the_rule_required_one():
    out, r_flag = _derive(False)
    assert out == frozenset({FCC, ENC}) and r_flag.called


def test_the_rule_only_set_holds_just_the_rule_required_attribute():
    out, r_flag = _derive(True)
    assert out == frozenset({ENC}) and not r_flag.called


# --- the required set has its own guard setting; the constraint-rule applier does not read it ------------------------
RULE_GUARD_RULE = SimpleNamespace(mode="DISALLOW", blank=True, condition_script=None, conditions=[object()],
                                  guard_attr="sessionVariable_TER", target_attr_id=7)


def _rule_required(old_flag, new_flag):
    attr = SimpleNamespace(variable_name=ENC, entity_id=7)
    engine = SimpleNamespace(
        load_recommendation_and_constraint_rules=lambda *a, **k: ([], [RULE_GUARD_RULE]),
        load_validation_rules=lambda *a, **k: [])
    settings = SimpleNamespace(cpq_required_set_guards_assumed_open=old_flag,
                               cpq_required_set_rule_guards_assumed_open=new_flag)
    with patch.object(required_set, "get_settings", return_value=settings), \
            patch.object(required_set, "_attr_index", return_value={7: attr}), \
            patch.object(required_set, "_filled_by_rule_id", return_value={}), \
            patch.object(required_set, "_fires", return_value=True):
        return required_set.rule_required_vns(engine, [attr], {}, {}, 1267, "p")


def test_the_guarded_rule_needs_one_of_the_two_settings():
    assert _rule_required(False, False) == set()            # TER absent from the quote: the rule does not fire
    assert _rule_required(False, True) == {ENC}              # the new, required-set-only setting
    assert _rule_required(True, False) == {ENC}              # the older setting still works


def test_the_constraint_rule_applier_never_reads_the_required_set_only_setting():
    from pathlib import Path

    from aryx.cpq.constraint_rules import constraint_rules_apply
    source = Path(constraint_rules_apply.__file__).read_text(encoding="utf-8")
    assert "cpq_required_set_rule_guards_assumed_open" not in source
    assert "cpq_required_set_guards_assumed_open" in source   # it keeps its own, unchanged
