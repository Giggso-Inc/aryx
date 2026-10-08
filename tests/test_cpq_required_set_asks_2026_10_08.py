"""Ask asks the attributes the derived required set marks required (flag `cpq_required_set_asks_enabled`).

ws 1267, APX 900: Encryption Type is required by a blank-disallow rule (TER-gated) while attrSequence has it optional, so
no stage asked it and the quote completed without it. The derived required set (the one config_data and the summary
already use) now also makes such an attribute 'always ask, never guess'."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill import auto_fill_setup
from aryx.cpq.auto_fill_stages import governance_flags
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.state import ConfigAttr

ENC = "secureEncryptionType_astro"
OTHER = "someOptionalThing_astro"


def _attr(vn):
    return ConfigAttr(entity_id=abs(hash(vn)) % 100_000, variable_name=vn, display_label=vn, required=False,
                      default_value="", select_type="single", hidden=False, options=[])


def _ask(flag, derived=None, raises=False, workspace_id=1267):
    settings = SimpleNamespace(cpq_required_set_asks_enabled=flag)
    side = {"side_effect": RuntimeError("boom")} if raises else {"return_value": frozenset(derived or ())}
    with patch.object(auto_fill_setup, "get_settings", return_value=settings), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", **side) as derive:
        out = auto_fill_setup._required_ask_vns(
            SimpleNamespace(), [_attr(ENC), _attr(OTHER)], {}, {}, {}, None, workspace_id, "p", "APX 900", {})
    return out, derive


def test_the_derived_required_set_is_not_read_with_the_flag_off_or_without_a_workspace():
    out, derive = _ask(False, {ENC})
    assert out == frozenset() and not derive.called
    out, derive = _ask(True, {ENC}, workspace_id=None)
    assert out == frozenset() and not derive.called


def test_with_the_flag_the_derived_required_set_is_the_set_the_pass_asks():
    out, derive = _ask(True, {ENC})
    assert out == frozenset({ENC})
    assert derive.call_args.args[-3] == "p" or derive.called


def test_a_failure_while_deriving_leaves_the_pass_as_it_was():
    out, _ = _ask(True, raises=True)
    assert out == frozenset()


def _governance(attr, required):
    engine = SimpleNamespace(_is_hardware_version_attr=lambda a: False,
                             _hardware_version_confirmed_not_applicable=lambda *a, **k: True)
    scope = SimpleNamespace(
        base_model_narrowing=None, required_ask_vns=frozenset(required), display_order=None, skip_always_ask=None,
        governed=set(), rule_governed=set(), product_anchor_hint=None, workspace_id=1267, catalog_prefix="p",
        country="US", bm_region_allow_value=None)
    state = AttrResolution(vn=attr.variable_name, vn_flat=attr.variable_name.lower().replace("_", ""))
    governance_flags.stage_governance_flags(engine, attr, SimpleNamespace(dt_cache={}), scope, state)
    return state


def test_a_required_attribute_becomes_a_decision_attribute_and_others_are_untouched():
    assert _governance(_attr(ENC), {ENC}).is_decision_attr is True
    assert _governance(_attr(OTHER), {ENC}).is_decision_attr is False
    assert _governance(_attr(ENC), set()).is_decision_attr is False
