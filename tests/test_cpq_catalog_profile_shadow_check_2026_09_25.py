"""Tests for catalog_profile.shadow_check_role_vn and its gated wiring into
_invalidate_stale_base_model -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md's
T1 Phase 3 pilot slice (first slice of the proposed CatalogProfile design:
log-only comparison against today's hardcoded literal, never changing
behavior).
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model import (
    _BASE_MODEL_VN,
    _invalidate_stale_base_model,
)
from aryx.cpq.catalog_profile import shadow_check_role_vn
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


# ── gated wiring into _invalidate_stale_base_model ───────────────────────

def test_shadow_check_not_called_when_flag_disabled():
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: "BM_OLD"},
        display_filled={_BASE_MODEL_VN: "BM_OLD"},
        filled_source={_BASE_MODEL_VN: "cascade"},
    )
    hw_version = _attr(1, "hWVersion_astro")
    with (
        patch("aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.get_settings") as mock_cfg,
        patch(
            "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.shadow_check_role_vn",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = False
        _invalidate_stale_base_model(
            session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=704,
        )
    mock_shadow.assert_not_called()
    assert _BASE_MODEL_VN not in session.filled


def test_shadow_check_called_when_flag_enabled():
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: "BM_OLD"},
        display_filled={_BASE_MODEL_VN: "BM_OLD"},
        filled_source={_BASE_MODEL_VN: "cascade"},
    )
    hw_version = _attr(1, "hWVersion_astro")
    with (
        patch("aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.get_settings") as mock_cfg,
        patch(
            "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.shadow_check_role_vn",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        _invalidate_stale_base_model(
            session, hw_version, dependent_eids=set(), by_eid={}, workspace_id=704,
            catalog_prefix="Astro",
        )
    mock_shadow.assert_called_once_with(
        "Base Model", _BASE_MODEL_VN, "APX NEXT XE", 704, "Astro",
    )
    assert _BASE_MODEL_VN not in session.filled


def test_shadow_check_not_called_when_no_trigger_fires():
    """Even with the flag on, an unrelated attribute change must not
    invoke the shadow check at all -- it only runs inside the branch that
    actually pops Base Model."""
    session = CpqSession(
        product_name="APX NEXT XE",
        filled={_BASE_MODEL_VN: "BM_OLD", "billingOption_astro": "NET30"},
    )
    billing = _attr(3, "billingOption_astro")
    with (
        patch("aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.get_settings") as mock_cfg,
        patch(
            "aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model.shadow_check_role_vn",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.catalog_profile_shadow_check_enabled = True
        _invalidate_stale_base_model(
            session, billing, dependent_eids=set(), by_eid={}, workspace_id=704,
        )
    mock_shadow.assert_not_called()
    assert session.filled[_BASE_MODEL_VN] == "BM_OLD"
