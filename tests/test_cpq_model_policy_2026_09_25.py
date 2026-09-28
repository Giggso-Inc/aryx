"""Tests for model_policy.py -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md's
T6 Phase 3 pilot slice (the "legacy" arm of the proposed ModelPolicy
design, proven standalone before any real call site is touched) and
its follow-up shadow-check wiring into try_multi_optional_empty.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from aryx.cpq.auto_fill_stages.multi_optout_and_empty import try_multi_optional_empty
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.data_table_bridge.attr_governance import _CONFIRMED_DEAD_ATTRS
from aryx.cpq.engine import CpqEngine
from aryx.cpq.fill_signature import _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
from aryx.cpq.model_policy import (
    confirmed_dead_attrs,
    duplicate_display_name_canonical_item_value,
    optional_empty_fill_accepted_vns,
    recommended_config_only_vns,
    resolve_confirmed_dead_attr_membership,
    resolve_optional_empty_fill_membership,
    resolve_recommended_config_only_membership,
    resolve_select_all_narrowed_legal_multi_membership,
    select_all_narrowed_legal_multi_vns,
    shadow_check_optional_empty_fill_vns,
)
from aryx.cpq.opt_out_and_duplicates import (
    _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE,
    _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS,
)
from aryx.cpq.state import ConfigAttr


def test_optional_empty_fill_accepted_vns_matches_the_real_constant_for_apxnext():
    assert optional_empty_fill_accepted_vns("APXNEXT") == _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS


def test_optional_empty_fill_accepted_vns_case_insensitive_model_match():
    assert optional_empty_fill_accepted_vns("apxnext") == _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    assert optional_empty_fill_accepted_vns(" APXNEXT ") == _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS


def test_optional_empty_fill_accepted_vns_empty_for_unknown_model():
    """No policy entry for a model (e.g. SVX, not yet catalogued here)
    must never guess -- empty, matching this constant's own "individually
    verified only" discipline."""
    assert optional_empty_fill_accepted_vns("SVX") == frozenset()
    assert optional_empty_fill_accepted_vns("") == frozenset()
    assert optional_empty_fill_accepted_vns(None) == frozenset()


def test_duplicate_display_name_canonical_item_value_matches_the_real_constant_for_apxnext():
    assert (
        duplicate_display_name_canonical_item_value("APXNEXT")
        == _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE
    )


def test_duplicate_display_name_canonical_item_value_empty_for_unknown_model():
    assert duplicate_display_name_canonical_item_value("SVX") == {}
    assert duplicate_display_name_canonical_item_value("") == {}


def test_recommended_config_only_vns_matches_the_real_constant_for_apxnext():
    assert recommended_config_only_vns("APXNEXT") == CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS


def test_recommended_config_only_vns_case_insensitive_model_match():
    assert recommended_config_only_vns("apxnext") == CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS


def test_recommended_config_only_vns_empty_for_unknown_model():
    assert recommended_config_only_vns("SVX") == frozenset()
    assert recommended_config_only_vns("") == frozenset()
    assert recommended_config_only_vns(None) == frozenset()


def test_select_all_narrowed_legal_multi_vns_matches_the_real_constant_for_apxnext():
    assert (
        select_all_narrowed_legal_multi_vns("APXNEXT")
        == _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    )


def test_select_all_narrowed_legal_multi_vns_case_insensitive_model_match():
    assert (
        select_all_narrowed_legal_multi_vns("apxnext")
        == _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    )


def test_select_all_narrowed_legal_multi_vns_empty_for_unknown_model():
    assert select_all_narrowed_legal_multi_vns("SVX") == frozenset()
    assert select_all_narrowed_legal_multi_vns("") == frozenset()
    assert select_all_narrowed_legal_multi_vns(None) == frozenset()


def test_confirmed_dead_attrs_matches_the_real_constant_for_apxnext():
    assert confirmed_dead_attrs("APXNEXT") == _CONFIRMED_DEAD_ATTRS


def test_confirmed_dead_attrs_case_insensitive_model_match():
    assert confirmed_dead_attrs("apxnext") == _CONFIRMED_DEAD_ATTRS


def test_confirmed_dead_attrs_empty_for_unknown_model():
    assert confirmed_dead_attrs("SVX") == frozenset()
    assert confirmed_dead_attrs("") == frozenset()
    assert confirmed_dead_attrs(None) == frozenset()


def test_duplicate_display_name_canonical_item_value_returns_a_copy_not_the_live_dict():
    """Callers mutating the returned dict must never corrupt the module's
    own policy table for the next caller."""
    result = duplicate_display_name_canonical_item_value("APXNEXT")
    result["someNewKey_astro"] = "mutated"
    assert "someNewKey_astro" not in duplicate_display_name_canonical_item_value("APXNEXT")


# ── shadow_check_optional_empty_fill_vns itself ──────────────────────────

def test_optional_empty_shadow_check_logs_warning_on_mismatch(caplog):
    with (
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("SVX",)),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.model_policy"),
    ):
        shadow_check_optional_empty_fill_vns(
            "promoApplicationServices_astro", True, "Some SVX Product", 704,
        )
    assert any("ModelPolicy shadow mismatch" in r.message for r in caplog.records)


def test_optional_empty_shadow_check_silent_when_membership_agrees(caplog):
    with (
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("APXNEXT",)),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.model_policy"),
    ):
        shadow_check_optional_empty_fill_vns(
            "promoApplicationServices_astro", True, "APX NEXT XE", 704,
        )
    assert not any("mismatch" in r.message for r in caplog.records)


def test_optional_empty_shadow_check_noop_when_workspace_id_none():
    with patch("aryx.cpq.model_policy._cpq_model_candidates") as mock_candidates:
        shadow_check_optional_empty_fill_vns("some_vn", False, "Product", None)
    mock_candidates.assert_not_called()


def test_optional_empty_shadow_check_never_raises_even_if_resolver_blows_up():
    with patch(
        "aryx.cpq.model_policy._cpq_model_candidates", side_effect=RuntimeError("boom"),
    ):
        shadow_check_optional_empty_fill_vns("some_vn", True, "Product", 704)
    # No exception propagated -- that's the whole assertion.


# ── gated wiring into try_multi_optional_empty ───────────────────────────

def _attr(vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=vn, required=False,
        default_value="", select_type="multi", options=[],
    )


def _scope(workspace_id=704, catalog_prefix="Astro", grid_selector_vns=frozenset()):
    scope = MagicMock()
    scope.workspace_id = workspace_id
    scope.catalog_prefix = catalog_prefix
    scope.grid_selector_vns = grid_selector_vns
    return scope


def _ctx(product="APX NEXT XE"):
    ctx = MagicMock()
    ctx.filled = {"productSelectionProduct_all": product}
    ctx.filled_multi = {}
    ctx.display_filled = {}
    ctx.sources = {}
    ctx.dt_cache = {}
    return ctx


def test_optional_empty_wiring_calls_resolve_with_right_args():
    attr = _attr("promoApplicationServices_astro")
    state = AttrResolution(vn=attr.variable_name, allowed_for_attr=None)
    ctx = _ctx()
    scope = _scope()
    with patch(
        "aryx.cpq.auto_fill_stages.multi_optout_and_empty.resolve_optional_empty_fill_membership",
        return_value=True,
    ) as mock_resolve:
        result = try_multi_optional_empty(MagicMock(), attr, ctx, scope, state)
    mock_resolve.assert_called_once_with(
        "promoApplicationServices_astro", "APX NEXT XE", 704, "Astro", {},
    )
    assert result is True
    assert ctx.filled_multi["promoApplicationServices_astro"] == []


def test_optional_empty_wiring_does_not_fill_when_resolve_returns_false():
    """If model_policy resolution says this vn is NOT genuinely optional-
    empty for the session's actual model (only possible with
    model_policy_scoped_resolution_enabled on for a model with its own,
    distinct policy entry), the empty-fill branch must not fire."""
    attr = _attr("promoApplicationServices_astro")
    state = AttrResolution(vn=attr.variable_name, allowed_for_attr=None)
    with patch(
        "aryx.cpq.auto_fill_stages.multi_optout_and_empty.resolve_optional_empty_fill_membership",
        return_value=False,
    ):
        result = try_multi_optional_empty(MagicMock(), attr, _ctx(), _scope(), state)
    assert result is False


def test_optional_empty_wiring_not_called_for_a_single_select_attr():
    """A non-multi attr must never reach resolution at all -- it only
    runs inside the same guard the real branch always used (select_type
    == 'multi' and not required and not a grid selector)."""
    attr = ConfigAttr(
        entity_id=1, variable_name="someSingleSelect_astro", display_label="x",
        required=False, default_value="", select_type="single", options=[],
    )
    state = AttrResolution(vn=attr.variable_name)
    with patch(
        "aryx.cpq.auto_fill_stages.multi_optout_and_empty.resolve_optional_empty_fill_membership",
    ) as mock_resolve:
        try_multi_optional_empty(MagicMock(), attr, _ctx(), _scope(), state)
    mock_resolve.assert_not_called()


# ── resolve_optional_empty_fill_membership ────────────────────────────────
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3 "scoped" rollout
# safety note: same class of bug already caught once this session for
# catalog_profile.py's resolve_*_vn() functions -- the regression guard
# below asserts _cpq_model_candidates is never called at the real
# (unmocked) default.

def test_resolve_optional_empty_fill_membership_never_touches_candidates_when_flag_is_at_its_real_default():
    with patch(
        "aryx.cpq.model_policy._cpq_model_candidates",
    ) as mock_candidates:
        result = resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "APX NEXT XE", 704,
        )
    mock_candidates.assert_not_called()
    assert result is True


def test_resolve_optional_empty_fill_membership_matches_legacy_constant_at_real_default():
    assert resolve_optional_empty_fill_membership(
        "someUnrelatedVn_astro", "APX NEXT XE", 704,
    ) is False


def _enabled_settings():
    mock_cfg = MagicMock()
    mock_cfg.return_value.model_policy_scoped_resolution_enabled = True
    return patch("aryx.cpq.model_policy.get_settings", mock_cfg)


def test_resolve_optional_empty_fill_membership_falls_back_when_workspace_id_none():
    with _enabled_settings():
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "APX NEXT XE", None,
        ) is True


def test_resolve_optional_empty_fill_membership_falls_back_when_no_product():
    with _enabled_settings():
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "", 704,
        ) is True


def test_resolve_optional_empty_fill_membership_falls_back_when_candidates_raise():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.model_policy._cpq_model_candidates", side_effect=RuntimeError("boom"),
        ),
    ):
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "APX NEXT XE", 704,
        ) is True


def test_resolve_optional_empty_fill_membership_falls_back_when_no_candidates_resolve():
    with (
        _enabled_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=()),
    ):
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "APX NEXT XE", 704,
        ) is True


def test_resolve_optional_empty_fill_membership_uses_real_policy_when_candidates_resolve():
    with (
        _enabled_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("SVX",)),
    ):
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "Some SVX Product", 704,
        ) is False, "SVX has no policy entry -- real 'no membership', not a fallback"


def test_resolve_optional_empty_fill_membership_true_when_any_candidate_confirms():
    with (
        _enabled_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("SVX", "APXNEXT")),
    ):
        assert resolve_optional_empty_fill_membership(
            "promoApplicationServices_astro", "APX NEXT XE", 704,
        ) is True


# ── resolve_recommended_config_only_membership ────────────────────────────
# Unlike the other two resolvers, this one takes an already-resolved
# candidates tuple instead of resolving its own -- its one real caller
# (mandatory_tier_c_vns) already computes candidates unconditionally via
# the pre-existing, separately-cached _cpq_model_candidates, so there's
# no new RDB-touching call here to gate against a hung-test class of bug.
# `legacy_members` is passed explicitly (not imported) to preserve the
# CpqEngine class-attribute override contract -- see the function's own
# docstring and mandatory_tiers.py's module docstring.

def test_resolve_recommended_config_only_membership_matches_legacy_at_real_default():
    legacy = CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS
    assert resolve_recommended_config_only_membership(
        "packingPackageType_astro", legacy, ("APXNEXT",),
    ) is True
    assert resolve_recommended_config_only_membership(
        "someUnrelatedVn_astro", legacy, ("APXNEXT",),
    ) is False


def _enabled_model_policy_settings():
    mock_cfg = MagicMock()
    mock_cfg.return_value.model_policy_scoped_resolution_enabled = True
    return patch("aryx.cpq.model_policy.get_settings", mock_cfg)


def test_resolve_recommended_config_only_membership_falls_back_when_no_candidates():
    """No candidates resolved (e.g. mandatory_tier_c_vns's own early
    returns never even reach this call in practice, but the contract
    must hold regardless) falls back to legacy_members, not a guess --
    exercised with the gate ON so the "no cpq_models" branch, not just
    the flag-off early return, is actually what's being tested."""
    with _enabled_model_policy_settings():
        assert resolve_recommended_config_only_membership(
            "packingPackageType_astro", frozenset({"packingPackageType_astro"}), None,
        ) is True
        assert resolve_recommended_config_only_membership(
            "packingPackageType_astro", frozenset({"packingPackageType_astro"}), (),
        ) is True


def test_resolve_recommended_config_only_membership_falls_back_to_a_custom_legacy_set():
    """A subclass/instance override of engine._RECOMMENDED_CONFIG_ONLY_VNS
    must still be honored when the gate is off -- this is exactly why
    legacy_members is a parameter, not an import."""
    custom = frozenset({"someCustomVn_astro"})
    assert resolve_recommended_config_only_membership(
        "someCustomVn_astro", custom, None,
    ) is True
    assert resolve_recommended_config_only_membership(
        "packingPackageType_astro", custom, None,
    ) is False


def test_resolve_recommended_config_only_membership_uses_real_policy_when_gate_on():
    legacy = CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS
    with _enabled_model_policy_settings():
        assert resolve_recommended_config_only_membership(
            "packingPackageType_astro", legacy, ("SVX",),
        ) is False, "SVX has no policy entry -- real 'no membership', not a fallback"
        assert resolve_recommended_config_only_membership(
            "packingPackageType_astro", legacy, ("APXNEXT",),
        ) is True


def test_resolve_recommended_config_only_membership_true_when_any_candidate_confirms():
    legacy = CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS
    with _enabled_model_policy_settings():
        assert resolve_recommended_config_only_membership(
            "packingPackageType_astro", legacy, ("SVX", "APXNEXT"),
        ) is True


# ── resolve_select_all_narrowed_legal_multi_membership ─────────────────────
# Same shape as resolve_optional_empty_fill_membership -- resolves its own
# model candidates via product_name, since its one real caller
# (blind_pick_narrowed) has no already-resolved candidates tuple in local
# scope (unlike mandatory_tier_c_vns's case for the recommended-config-only
# resolver above).

def test_resolve_select_all_narrowed_legal_multi_membership_never_touches_candidates_when_flag_is_at_its_real_default():
    with patch("aryx.cpq.model_policy._cpq_model_candidates") as mock_candidates:
        result = resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "APX NEXT XE", 704,
        )
    mock_candidates.assert_not_called()
    assert result is True


def test_resolve_select_all_narrowed_legal_multi_membership_matches_legacy_constant_at_real_default():
    assert resolve_select_all_narrowed_legal_multi_membership(
        "someUnrelatedVn_astro", "APX NEXT XE", 704,
    ) is False


def test_resolve_select_all_narrowed_legal_multi_membership_falls_back_when_workspace_id_none():
    with _enabled_model_policy_settings():
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "APX NEXT XE", None,
        ) is True


def test_resolve_select_all_narrowed_legal_multi_membership_falls_back_when_no_product():
    with _enabled_model_policy_settings():
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "", 704,
        ) is True


def test_resolve_select_all_narrowed_legal_multi_membership_falls_back_when_candidates_raise():
    with (
        _enabled_model_policy_settings(),
        patch(
            "aryx.cpq.model_policy._cpq_model_candidates", side_effect=RuntimeError("boom"),
        ),
    ):
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "APX NEXT XE", 704,
        ) is True


def test_resolve_select_all_narrowed_legal_multi_membership_falls_back_when_no_candidates_resolve():
    with (
        _enabled_model_policy_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=()),
    ):
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "APX NEXT XE", 704,
        ) is True


def test_resolve_select_all_narrowed_legal_multi_membership_uses_real_policy_when_candidates_resolve():
    with (
        _enabled_model_policy_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("SVX",)),
    ):
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "Some SVX Product", 704,
        ) is False, "SVX has no policy entry -- real 'no membership', not a fallback"


def test_resolve_select_all_narrowed_legal_multi_membership_true_when_any_candidate_confirms():
    with (
        _enabled_model_policy_settings(),
        patch("aryx.cpq.model_policy._cpq_model_candidates", return_value=("SVX", "APXNEXT")),
    ):
        assert resolve_select_all_narrowed_legal_multi_membership(
            "modelSelectionFrequencyBandMsl_astro", "APX NEXT XE", 704,
        ) is True


# ── resolve_confirmed_dead_attr_membership ──────────────────────────────
# Same shape as resolve_recommended_config_only_membership -- takes an
# already-resolved candidates tuple (its one real caller,
# _suppress_ungoverned_attrs, already computes them unconditionally) and
# legacy_members as a parameter (not an import -- attr_governance.py
# already imports resolve_confirmed_dead_attr_membership itself, lazily,
# to sidestep a genuine circular import; model_policy.py importing the
# constant back would reintroduce it).

def test_resolve_confirmed_dead_attr_membership_matches_legacy_at_real_default():
    assert resolve_confirmed_dead_attr_membership(
        "modelSelectionFrequencyBands_astro", _CONFIRMED_DEAD_ATTRS, ("APXNEXT",),
    ) is True
    assert resolve_confirmed_dead_attr_membership(
        "someUnrelatedVn_astro", _CONFIRMED_DEAD_ATTRS, ("APXNEXT",),
    ) is False


def test_resolve_confirmed_dead_attr_membership_falls_back_when_no_candidates():
    with _enabled_model_policy_settings():
        assert resolve_confirmed_dead_attr_membership(
            "modelSelectionFrequencyBands_astro",
            frozenset({"modelSelectionFrequencyBands_astro"}), None,
        ) is True
        assert resolve_confirmed_dead_attr_membership(
            "modelSelectionFrequencyBands_astro",
            frozenset({"modelSelectionFrequencyBands_astro"}), (),
        ) is True


def test_resolve_confirmed_dead_attr_membership_falls_back_to_a_custom_legacy_set():
    custom = frozenset({"someCustomVn_astro"})
    assert resolve_confirmed_dead_attr_membership(
        "someCustomVn_astro", custom, None,
    ) is True
    assert resolve_confirmed_dead_attr_membership(
        "modelSelectionFrequencyBands_astro", custom, None,
    ) is False


def test_resolve_confirmed_dead_attr_membership_uses_real_policy_when_gate_on():
    with _enabled_model_policy_settings():
        assert resolve_confirmed_dead_attr_membership(
            "modelSelectionFrequencyBands_astro", _CONFIRMED_DEAD_ATTRS, ("SVX",),
        ) is False, "SVX has no policy entry -- real 'no membership', not a fallback"
        assert resolve_confirmed_dead_attr_membership(
            "modelSelectionFrequencyBands_astro", _CONFIRMED_DEAD_ATTRS, ("APXNEXT",),
        ) is True


def test_resolve_confirmed_dead_attr_membership_true_when_any_candidate_confirms():
    with _enabled_model_policy_settings():
        assert resolve_confirmed_dead_attr_membership(
            "modelSelectionFrequencyBands_astro", _CONFIRMED_DEAD_ATTRS, ("SVX", "APXNEXT"),
        ) is True
