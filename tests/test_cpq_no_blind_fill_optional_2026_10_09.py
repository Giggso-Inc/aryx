"""Optional attributes with no basis are left unanswered (flag `cpq_no_blind_fill_optional_enabled`).

ws 1267, APX 3000: Mission Critical Wireless Accessory Bundle (optional, no default) was filled Pack 1 by a blind
first-option stage and went into the BOM."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill_stages import optional_blind_guard as guard
from aryx.cpq.auto_fill_stages import tier6_single_b as tier6
from aryx.cpq.state import ConfigAttr, MenuOption

VN = "spMissionCriticalWirelessAccessoryBundles_astro"


def _attr(required=False, select_type="single"):
    opts = [MenuOption(item_value=f"PACK {i}", display_name=f"Pack {i}", order=i) for i in (1, 2, 3)]
    return ConfigAttr(entity_id=11, variable_name=VN, display_label="Bundle", required=required, default_value="",
                      select_type=select_type, hidden=False, options=opts)


def _on(flag=True):
    return patch.object(guard, "get_settings", return_value=SimpleNamespace(cpq_no_blind_fill_optional_enabled=flag))


def test_flag_off_changes_nothing():
    with _on(False):
        assert guard.optional_without_basis(_attr(), SimpleNamespace(is_decision_attr=False)) is False


def test_flag_on_skips_an_optional_single_select_without_basis():
    with _on():
        assert guard.optional_without_basis(_attr(), SimpleNamespace(is_decision_attr=False)) is True


def test_required_decision_and_multi_attributes_are_never_skipped():
    with _on():
        assert guard.optional_without_basis(_attr(required=True), SimpleNamespace(is_decision_attr=False)) is False
        assert guard.optional_without_basis(_attr(), SimpleNamespace(is_decision_attr=True)) is False
        assert guard.optional_without_basis(_attr(select_type="multi"), SimpleNamespace(is_decision_attr=False)) is False


def test_a_mock_settings_object_cannot_turn_it_on():
    with patch.object(guard, "get_settings", return_value=object()):
        assert guard.optional_without_basis(_attr(), SimpleNamespace(is_decision_attr=False)) is False


def _tail(flag):
    attr = _attr()
    state = SimpleNamespace(vn=VN, valid_opts=attr.options, is_decision_attr=False, value=None, display=None,
                            source=None, governed_source="blind_pick_governed")
    ctx = SimpleNamespace(filled={}, dt_cache={})
    scope = SimpleNamespace(display_order={VN: 1}, rec_by_target={}, workspace_id=1267, catalog_prefix="p")
    with _on(flag), \
            patch.object(tier6, "resolve_blind_fill_risk_accepted_membership", return_value=True), \
            patch.object(tier6, "scoped_first_available", return_value=None), \
            patch.object(tier6, "inferred_first_available", return_value=None), \
            patch.object(tier6.fill_log, "log_decision"):
        tier6.single_chain_tail(SimpleNamespace(), attr, ctx, scope, state)
    return state


def test_the_tail_stage_guesses_pack_1_today_and_leaves_it_open_with_the_flag():
    assert _tail(False).value == "PACK 1" and _tail(False).source == "default_first_available"
    on = _tail(True)
    assert on.value is None and on.source is None
