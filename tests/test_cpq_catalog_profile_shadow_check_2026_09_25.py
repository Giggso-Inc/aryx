"""Tests for catalog_profile.shadow_check_role_vn and its gated wiring into
_invalidate_stale_base_model -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md's
T1 Phase 3 pilot slice (first slice of the proposed CatalogProfile design:
log-only comparison against today's hardcoded literal, never changing
behavior).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model import (
    _BASE_MODEL_VN,
    _invalidate_stale_base_model,
)
from aryx.cpq.catalog_profile import CatalogProfile, shadow_check_role_vn
from aryx.cpq.payload_building.anchor_exclusions import _data_table_resolved_anchor_vns
from aryx.cpq.rules_loop.rules_loop_pass_early import run_early_pass
from aryx.cpq.rules_loop.rules_loop_state import LoopScope, LoopState
from aryx.cpq.state import ConfigAttr, CpqSession


def _attr(entity_id: int, variable_name: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, source_id=entity_id, variable_name=variable_name,
        display_label=variable_name, required=False, default_value="", options=[],
    )


# ── shadow_check_role_vn itself ──────────────────────────────────────────

def test_shadow_check_logs_warning_on_mismatch(caplog):
    with (
        patch("aryx.cpq.catalog_profile._cpq_model_candidates", return_value=("APXNEXT",)),
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="someOtherVarName_astro",
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704)
    assert any("CatalogProfile shadow mismatch" in r.message for r in caplog.records)


def test_shadow_check_silent_when_resolved_matches_literal(caplog):
    with (
        patch("aryx.cpq.catalog_profile._cpq_model_candidates", return_value=("APXNEXT",)),
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="modelSelectionbaseModel_astro",
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704)
    assert not any("mismatch" in r.message for r in caplog.records)


def test_shadow_check_silent_when_resolver_returns_none(caplog):
    with (
        patch("aryx.cpq.catalog_profile._cpq_model_candidates", return_value=("APXNEXT",)),
        patch("aryx.cpq.catalog_profile.resolve_variable_name_for_role", return_value=None),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704)
    assert not any("mismatch" in r.message for r in caplog.records)


def test_shadow_check_never_raises_even_if_resolver_blows_up():
    with patch(
        "aryx.cpq.catalog_profile._cpq_model_candidates",
        side_effect=RuntimeError("boom"),
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704)
    # No exception propagated -- that's the whole assertion.


# ── real resolution wired into _invalidate_stale_base_model ─────────────
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 "scoped" rollout:
# the pilot slice's gated shadow_check_role_vn call was replaced by an
# unconditional call to resolve_base_model_vn(), which is itself gated
# internally (catalog_profile_scoped_resolution_enabled, see catalog_
# profile.py) -- see test_cpq_catalog_profile_scoped_resolution_2026_09_
# 25.py for that function's own tests. These tests only cover this call
# site's wiring: it must call resolve_base_model_vn with the right
# arguments and pop under whatever key it returns.

def test_resolve_base_model_vn_is_called_and_its_result_is_popped():
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: "BM_OLD"},
        display_filled={_BASE_MODEL_VN: "BM_OLD"},
        filled_source={_BASE_MODEL_VN: "cascade"},
    )
    hw_version = _attr(1, "hWVersion_astro")
    with patch(
        "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.resolve_base_model_vn",
        return_value=_BASE_MODEL_VN,
    ) as mock_resolve:
        _invalidate_stale_base_model(
            session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=704,
            catalog_prefix="Astro",
        )
    mock_resolve.assert_called_once_with(session.filled, 704, "Astro")
    assert _BASE_MODEL_VN not in session.filled


def test_pops_under_whatever_key_resolve_base_model_vn_returns():
    """If resolve_base_model_vn ever resolves to a DIFFERENT key than the
    literal (only possible with catalog_profile_scoped_resolution_enabled
    turned on for a workspace with real attrToVarMapping coverage), the
    pop must follow that resolved key, not the hardcoded literal --
    otherwise the stale value would never actually get cleared."""
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={"someOtherCatalogsBaseModelVn": "BM_OLD", _BASE_MODEL_VN: "unrelated"},
        display_filled={"someOtherCatalogsBaseModelVn": "BM_OLD"},
        filled_source={"someOtherCatalogsBaseModelVn": "cascade"},
    )
    hw_version = _attr(1, "hWVersion_astro")
    with patch(
        "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.resolve_base_model_vn",
        return_value="someOtherCatalogsBaseModelVn",
    ):
        _invalidate_stale_base_model(
            session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=704,
        )
    assert "someOtherCatalogsBaseModelVn" not in session.filled
    assert "someOtherCatalogsBaseModelVn" not in session.display_filled
    assert "someOtherCatalogsBaseModelVn" not in session.filled_source
    # The literal key is untouched -- it was never the real key here.
    assert session.filled[_BASE_MODEL_VN] == "unrelated"


def test_resolve_base_model_vn_not_called_when_no_trigger_fires():
    """An unrelated attribute change must not invoke resolution at all --
    it only runs inside the branch that actually pops Base Model."""
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: "BM_OLD", "billingOption_astro": "NET30"},
    )
    billing = _attr(3, "billingOption_astro")
    with patch(
        "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.resolve_base_model_vn",
    ) as mock_resolve:
        _invalidate_stale_base_model(
            session, billing, dependent_eids=set(), by_eid={}, workspace_id=704,
        )
    mock_resolve.assert_not_called()
    assert session.filled[_BASE_MODEL_VN] == "BM_OLD"


# ── gated wiring into _data_table_resolved_anchor_vns (Region role) ─────

def test_region_shadow_check_not_called_when_flag_disabled():
    filled = {
        "productSelectionProduct_all": "APX NEXT ENHANCED",
        "ultimateDestinationCountry": "United States",
    }
    attr = _attr(1, "modelSelectionbaseModel_astro")
    with (
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.shadow_check_role_vn",
        ) as mock_shadow,
        patch("aryx.cpq.engine._cpq_model_candidates", return_value=()),
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = False
        _data_table_resolved_anchor_vns(None, filled, [attr], 704)
    mock_shadow.assert_not_called()


def test_region_shadow_check_called_when_flag_enabled():
    filled = {
        "productSelectionProduct_all": "APX NEXT ENHANCED",
        "ultimateDestinationCountry": "United States",
    }
    attr = _attr(1, "modelSelectionbaseModel_astro")
    with (
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.shadow_check_role_vn",
        ) as mock_shadow,
        patch("aryx.cpq.engine._cpq_model_candidates", return_value=()),
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        _data_table_resolved_anchor_vns(None, filled, [attr], 704, "Astro")
    mock_shadow.assert_called_once_with(
        "Region", "modelSelectionRegion_astro", "APX NEXT ENHANCED", 704, "Astro", None,
    )


def test_region_shadow_check_not_called_when_no_product():
    """Even with the flag on, an empty product must not invoke the shadow
    check at all -- it only runs after the function's own early-return
    guards for filled/attrs/workspace_id/product."""
    with (
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.payload_building.anchor_exclusions.shadow_check_role_vn",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        result = _data_table_resolved_anchor_vns(None, {}, [_attr(1, "x")], 704)
    mock_shadow.assert_not_called()
    assert result == frozenset()


# ── CatalogProfile class itself ──────────────────────────────────────────

def test_for_product_resolves_cpq_models_once():
    with patch(
        "aryx.cpq.catalog_profile._cpq_model_candidates", return_value=("APXNEXT", "APXNEXT_BOM"),
    ) as mock_candidates:
        profile = CatalogProfile.for_product("Product X", 704, "Astro")
    mock_candidates.assert_called_once_with("Product X", 704, "Astro", None)
    assert profile.workspace_id == 704
    assert profile.catalog_prefix == "Astro"
    assert profile.cpq_models == ("APXNEXT", "APXNEXT_BOM")


def test_resolved_vn_returns_first_matching_candidates_result():
    profile = CatalogProfile(
        workspace_id=704, catalog_prefix="", cpq_models=("APXNEXT", "APXNEXT_BOM"),
    )
    with patch(
        "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
        side_effect=lambda model, role, *a, **k: (
            "modelSelectionbaseModel_astro" if model == "APXNEXT" else None
        ),
    ) as mock_resolve:
        assert profile.resolved_vn("Base Model") == "modelSelectionbaseModel_astro"
    # Only the first (matching) candidate needs to be tried.
    mock_resolve.assert_called_once()


def test_resolved_vn_tries_every_candidate_before_giving_up():
    profile = CatalogProfile(
        workspace_id=704, catalog_prefix="", cpq_models=("APXNEXT", "APXNEXT_BOM"),
    )
    with patch(
        "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
        side_effect=lambda model, role, *a, **k: (
            "modelSelectionbaseModel_astro" if model == "APXNEXT_BOM" else None
        ),
    ):
        assert profile.resolved_vn("Base Model") == "modelSelectionbaseModel_astro"


def test_resolved_vn_none_when_no_candidate_resolves():
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APXNEXT",))
    with patch("aryx.cpq.catalog_profile.resolve_variable_name_for_role", return_value=None):
        assert profile.resolved_vn("Some Unmapped Role") is None


def test_shadow_check_on_the_class_logs_mismatch(caplog):
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APXNEXT",))
    with (
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="someOtherVarName_astro",
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        profile.shadow_check("Base Model", "modelSelectionbaseModel_astro")
    assert any("CatalogProfile shadow mismatch" in r.message for r in caplog.records)


def test_shadow_check_on_the_class_never_raises():
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APXNEXT",))
    with patch(
        "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
        side_effect=RuntimeError("boom"),
    ):
        profile.shadow_check("Base Model", "modelSelectionbaseModel_astro")
    # No exception propagated -- that's the whole assertion.


def test_shadow_check_role_vn_wrapper_delegates_to_a_fresh_profile():
    """The backward-compatible free function must build exactly one
    CatalogProfile per call and delegate to its shadow_check -- not
    duplicate the comparison logic."""
    with (
        patch("aryx.cpq.catalog_profile._cpq_model_candidates", return_value=("APXNEXT",)),
        patch.object(CatalogProfile, "shadow_check") as mock_method,
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704, "Astro")
    mock_method.assert_called_once_with("Base Model", "modelSelectionbaseModel_astro")


def test_shadow_check_role_vn_wrapper_never_raises_if_candidates_lookup_fails():
    with patch(
        "aryx.cpq.catalog_profile._cpq_model_candidates", side_effect=RuntimeError("boom"),
    ):
        shadow_check_role_vn("Base Model", "modelSelectionbaseModel_astro", "Product X", 704)
    # No exception propagated -- that's the whole assertion.


# ── gated wiring into run_early_pass (Hidden Master String role) ────────

def _loop_state(**overrides) -> LoopState:
    defaults = dict(
        attrs=[], filled={"productSelectionProduct_all": "APX NEXT XE"},
        display_filled={}, sources={}, multi={}, dropped={},
    )
    defaults.update(overrides)
    return LoopState(**defaults)


def _loop_scope(**overrides) -> LoopScope:
    defaults = dict(
        hints={}, hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        country=None, negated_vns=None, skip_always_ask=None, display_order=None,
        workspace_id=704, catalog_prefix="Astro",
    )
    defaults.update(overrides)
    return LoopScope(**defaults)


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine._compute_hidden_master_string.return_value = None
    engine.apply_hiding_rules.return_value = ([], [], set())
    engine._suppress_ungoverned_attrs.return_value = ([], set())
    return engine


def test_hidden_master_string_shadow_check_not_called_when_flag_disabled():
    with (
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.shadow_check_role_vn",
        ) as mock_shadow,
        patch("aryx.cpq.rules_loop.rules_loop_pass_early.run_autofill_step"),
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = False
        run_early_pass(_mock_engine(), 1, _loop_state(), _loop_scope())
    mock_shadow.assert_not_called()


def test_hidden_master_string_shadow_check_called_when_flag_enabled():
    with (
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.shadow_check_role_vn",
        ) as mock_shadow,
        patch("aryx.cpq.rules_loop.rules_loop_pass_early.run_autofill_step"),
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        run_early_pass(_mock_engine(), 1, _loop_state(), _loop_scope())
    mock_shadow.assert_called_once_with(
        "Hidden Master String", "hiddenMasterStringForAstroPortable_astro",
        "APX NEXT XE", 704, "Astro", {},
    )


def test_hidden_master_string_shadow_check_skipped_when_already_computed_for_current_key():
    """Even with the flag on, a pass where the hidden-master-string cache
    is already fresh (matches _hidden_ms_key) must not re-run the shadow
    check -- it only runs inside the same recompute guard as the real
    _compute_hidden_master_string call."""
    state = _loop_state(filled={
        "productSelectionProduct_all": "APX NEXT XE",
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "hiddenMasterStringForAstroPortable_astro": "x@@@",
        "_hiddenMasterStringForAstroPortable_astro_computed_for": "APX NEXT XE\x1fH55TGT9PW8AN",
    })
    with (
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.rules_loop.rules_loop_pass_early.shadow_check_role_vn",
        ) as mock_shadow,
        patch("aryx.cpq.rules_loop.rules_loop_pass_early.run_autofill_step"),
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        run_early_pass(_mock_engine(), 1, state, _loop_scope())
    mock_shadow.assert_not_called()
