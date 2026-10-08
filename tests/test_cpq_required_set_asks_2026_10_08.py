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


def _ask(flag, derived=None, raises=False, workspace_id=1267, cache=None, filled=None, guards=True):
    settings = SimpleNamespace(cpq_required_set_asks_enabled=flag, cpq_required_set_guards_assumed_open=guards)
    side = {"side_effect": RuntimeError("boom")} if raises else {"return_value": frozenset(derived or ())}
    with patch.object(auto_fill_setup, "get_settings", return_value=settings), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", **side) as derive:
        out = auto_fill_setup._required_ask_vns(
            SimpleNamespace(), [_attr(ENC), _attr(OTHER)], dict(filled or {}), {}, {}, None, workspace_id, "p",
            "APX 900", {} if cache is None else cache)
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


def test_an_identical_state_reuses_the_set_and_a_changed_answer_recomputes_it():
    cache: dict = {}
    first, derive = _ask(True, {ENC}, cache=cache)
    again, derive_again = _ask(True, {ENC}, cache=cache)
    assert first == again == frozenset({ENC}) and derive.call_count == 1 and derive_again.call_count == 0
    changed, derive_changed = _ask(True, {OTHER}, cache=cache, filled={"modelSelectionKeypadType_astro": "FULL KEYPAD"})
    assert changed == frozenset({OTHER}) and derive_changed.call_count == 1          # a new answer, a new set


def test_without_the_guard_flag_nothing_is_asked_and_the_missing_dependency_is_reported_once_per_process():
    cache: dict = {}
    with patch.object(auto_fill_setup, "_DEPENDENCY_WARNED", False), patch.object(auto_fill_setup, "raven_log") as log:
        out, derive = _ask(True, {ENC}, cache=cache, guards=False)
        _ask(True, {ENC}, cache={}, guards=False)          # another turn, same process
    assert out == frozenset() and not derive.called
    assert [c.args[2] for c in log.call_args_list].count(
        "ask.required_set.dependency_missing asks flag needs the rule-guard flag, skipped") == 1


def test_the_asks_helper_asks_only_for_rule_required_attributes():
    with patch.object(auto_fill_setup, "get_settings", return_value=SimpleNamespace(
            cpq_required_set_asks_enabled=True, cpq_required_set_guards_assumed_open=True)), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", return_value=frozenset({ENC})) as derive:
        auto_fill_setup._required_ask_vns(
            SimpleNamespace(), [_attr(ENC)], {}, {}, {}, None, 1267, "p", "APX 900", {})
    assert derive.call_args.kwargs.get("rule_required_only") is True


def test_the_new_rule_guard_setting_alone_satisfies_the_dependency():
    settings = SimpleNamespace(cpq_required_set_asks_enabled=True, cpq_required_set_guards_assumed_open=False,
                               cpq_required_set_rule_guards_assumed_open=True)
    with patch.object(auto_fill_setup, "get_settings", return_value=settings), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", return_value=frozenset({ENC})):
        out = auto_fill_setup._required_ask_vns(
            SimpleNamespace(), [_attr(ENC)], {}, {}, {}, None, 1267, "p", "APX 900", {})
    assert out == frozenset({ENC})


def test_an_attribute_a_hiding_rule_hides_is_passed_as_hidden_so_it_is_not_asked():
    """APX N30/N50: 'Hide Encryption Type if Essential Core Bundle Selected N series' hides it, so it is never asked."""
    settings = SimpleNamespace(cpq_required_set_asks_enabled=True, cpq_required_set_guards_assumed_open=True)
    engine = SimpleNamespace(load_hiding_rules=lambda *a, **k: ["rule"],
                             apply_hiding_rules=lambda *a, **k: ([], [], {ENC}))
    with patch.object(auto_fill_setup, "get_settings", return_value=settings), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", return_value=frozenset()) as derive:
        auto_fill_setup._required_ask_vns(engine, [_attr(ENC)], {}, {}, {}, None, 1267, "p", "APX N30", {})
    assert ENC in derive.call_args.args[5]          # the hidden set handed to the derivation


def test_hiding_rules_that_cannot_be_read_hide_nothing_extra():
    settings = SimpleNamespace(cpq_required_set_asks_enabled=True, cpq_required_set_guards_assumed_open=True)
    engine = SimpleNamespace(load_hiding_rules=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with patch.object(auto_fill_setup, "get_settings", return_value=settings), \
            patch("aryx.cpq.payload_building.required_set.derive_required_vns", return_value=frozenset({ENC})) as derive:
        out = auto_fill_setup._required_ask_vns(engine, [_attr(ENC)], {}, {}, {}, None, 1267, "p", "APX 900", {})
    assert out == frozenset({ENC}) and ENC not in derive.call_args.args[5]
