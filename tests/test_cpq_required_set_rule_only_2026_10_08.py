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
