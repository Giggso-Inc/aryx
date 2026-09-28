"""Tests for catalog_profile.py's "scoped" real-resolution API --
CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3: CatalogProfile.
resolved_vn_or() and resolve_base_model_vn(), which actually GOVERN a
real decision (unlike shadow_check_role_vn, which only observes).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from aryx.cpq.catalog_profile import (
    BASE_MODEL_LITERAL,
    HIDDEN_MASTER_STRING_LITERAL,
    REGION_LITERAL,
    CatalogProfile,
    resolve_base_model_vn,
    resolve_hidden_master_string_vn,
    resolve_region_vn,
)


# ── CatalogProfile.resolved_vn_or ────────────────────────────────────────

def test_resolved_vn_or_returns_resolved_value_when_available():
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with patch(
        "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
        return_value="realVarName_astro",
    ):
        assert profile.resolved_vn_or("Base Model", "literalVarName_astro") == "realVarName_astro"


def test_resolved_vn_or_falls_back_to_literal_when_unresolved():
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with patch("aryx.cpq.catalog_profile.resolve_variable_name_for_role", return_value=None):
        assert profile.resolved_vn_or("Base Model", "literalVarName_astro") == "literalVarName_astro"


def test_resolved_vn_or_falls_back_to_literal_on_exception():
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with patch(
        "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
        side_effect=RuntimeError("boom"),
    ):
        assert profile.resolved_vn_or("Base Model", "literalVarName_astro") == "literalVarName_astro"


def test_resolved_vn_or_logs_when_resolved_differs_from_literal(caplog):
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with (
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="realVarName_astro",
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        profile.resolved_vn_or("Base Model", "literalVarName_astro")
    assert any("resolved a different variable_name" in r.message for r in caplog.records)


def test_resolved_vn_or_silent_when_resolved_matches_literal(caplog):
    profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with (
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="literalVarName_astro",
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.catalog_profile"),
    ):
        profile.resolved_vn_or("Base Model", "literalVarName_astro")
    assert not any("different variable_name" in r.message for r in caplog.records)


# ── resolve_base_model_vn ─────────────────────────────────────────────────
#
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 "scoped" rollout
# safety note: an EARLIER version of resolve_base_model_vn had no flag
# gate at all -- a hung unit test caught, before it shipped, that this
# makes a real, uncached ~265s-class RDB round trip on every call with a
# real filled/workspace_id, now from ~16 call sites across the codebase,
# several in hot loops. Fixed by checking catalog_profile_scoped_
# resolution_enabled FIRST, before any other work -- the test below is
# the regression guard for that specific class of bug: with the flag at
# its real default (False, not mocked), CatalogProfile.for_product must
# never be called at all, for any input.

def test_resolve_base_model_vn_never_touches_catalog_profile_when_flag_is_at_its_real_default():
    """No mocking of get_settings here -- this exercises the REAL default
    (False). If this ever calls CatalogProfile.for_product, it will hang
    for minutes against a real workspace instead of failing fast, exactly
    the bug this flag exists to prevent."""
    with patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product:
        result = resolve_base_model_vn({"productSelectionProduct_all": "APX NEXT XE"}, 704)
    mock_for_product.assert_not_called()
    assert result == BASE_MODEL_LITERAL


def test_resolve_base_model_vn_falls_back_when_filled_is_none():
    assert resolve_base_model_vn(None, 704) == BASE_MODEL_LITERAL


def test_resolve_base_model_vn_falls_back_when_filled_is_empty():
    assert resolve_base_model_vn({}, 704) == BASE_MODEL_LITERAL


def test_resolve_base_model_vn_falls_back_when_workspace_id_is_none():
    assert resolve_base_model_vn({"productSelectionProduct_all": "X"}, None) == BASE_MODEL_LITERAL


def test_resolve_base_model_vn_falls_back_when_no_product():
    assert resolve_base_model_vn({"someOtherKey": "y"}, 704) == BASE_MODEL_LITERAL


def _enabled_settings():
    mock_cfg = MagicMock()
    mock_cfg.return_value.catalog_profile_scoped_resolution_enabled = True
    return patch("aryx.cpq.catalog_profile.get_settings", mock_cfg)


def test_resolve_base_model_vn_falls_back_when_for_product_raises():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.catalog_profile.CatalogProfile.for_product",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert resolve_base_model_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == BASE_MODEL_LITERAL


def test_resolve_base_model_vn_returns_resolved_value_when_available():
    fake_profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product", return_value=fake_profile),
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="realVarName_astro",
        ),
    ):
        assert resolve_base_model_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == "realVarName_astro"


def test_resolve_base_model_vn_uses_product_and_workspace_from_filled():
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product,
    ):
        mock_for_product.return_value.resolved_vn_or.return_value = BASE_MODEL_LITERAL
        resolve_base_model_vn(
            {"productSelectionProduct_all": "APX NEXT XE"}, 704, "Astro", {"k": "v"},
        )
    mock_for_product.assert_called_once_with("APX NEXT XE", 704, "Astro", {"k": "v"})


# ── resolve_region_vn ──────────────────────────────────────────────────────
# Same shape, same gate, same safety rationale as resolve_base_model_vn
# above -- see its own comment block. Region is the second literal in
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3's full switch-over.

def test_resolve_region_vn_never_touches_catalog_profile_when_flag_is_at_its_real_default():
    """No mocking of get_settings here -- this exercises the REAL default
    (False). If this ever calls CatalogProfile.for_product, it will hang
    for minutes against a real workspace instead of failing fast."""
    with patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product:
        result = resolve_region_vn({"productSelectionProduct_all": "APX NEXT XE"}, 704)
    mock_for_product.assert_not_called()
    assert result == REGION_LITERAL


def test_resolve_region_vn_falls_back_when_filled_is_none():
    assert resolve_region_vn(None, 704) == REGION_LITERAL


def test_resolve_region_vn_falls_back_when_filled_is_empty():
    assert resolve_region_vn({}, 704) == REGION_LITERAL


def test_resolve_region_vn_falls_back_when_workspace_id_is_none():
    assert resolve_region_vn({"productSelectionProduct_all": "X"}, None) == REGION_LITERAL


def test_resolve_region_vn_falls_back_when_no_product():
    assert resolve_region_vn({"someOtherKey": "y"}, 704) == REGION_LITERAL


def test_resolve_region_vn_falls_back_when_for_product_raises():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.catalog_profile.CatalogProfile.for_product",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert resolve_region_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == REGION_LITERAL


def test_resolve_region_vn_returns_resolved_value_when_available():
    fake_profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product", return_value=fake_profile),
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="realRegionVarName_astro",
        ),
    ):
        assert resolve_region_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == "realRegionVarName_astro"


def test_resolve_region_vn_uses_product_and_workspace_from_filled():
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product,
    ):
        mock_for_product.return_value.resolved_vn_or.return_value = REGION_LITERAL
        resolve_region_vn(
            {"productSelectionProduct_all": "APX NEXT XE"}, 704, "Astro", {"k": "v"},
        )
    mock_for_product.assert_called_once_with("APX NEXT XE", 704, "Astro", {"k": "v"})


# ── resolve_hidden_master_string_vn ────────────────────────────────────────
# Same shape, same gate, same safety rationale as resolve_base_model_vn/
# resolve_region_vn above -- see resolve_base_model_vn's own comment. This
# is the third and final literal in CPQ_Hardcode_Audit_dev_oci_2026-09-25.md
# T1 Phase 3's full switch-over.

def test_resolve_hidden_master_string_vn_never_touches_catalog_profile_when_flag_is_at_its_real_default():
    """No mocking of get_settings here -- this exercises the REAL default
    (False). If this ever calls CatalogProfile.for_product, it will hang
    for minutes against a real workspace instead of failing fast."""
    with patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product:
        result = resolve_hidden_master_string_vn(
            {"productSelectionProduct_all": "APX NEXT XE"}, 704,
        )
    mock_for_product.assert_not_called()
    assert result == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_falls_back_when_filled_is_none():
    assert resolve_hidden_master_string_vn(None, 704) == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_falls_back_when_filled_is_empty():
    assert resolve_hidden_master_string_vn({}, 704) == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_falls_back_when_workspace_id_is_none():
    assert resolve_hidden_master_string_vn(
        {"productSelectionProduct_all": "X"}, None,
    ) == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_falls_back_when_no_product():
    assert resolve_hidden_master_string_vn(
        {"someOtherKey": "y"}, 704,
    ) == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_falls_back_when_for_product_raises():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.catalog_profile.CatalogProfile.for_product",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert resolve_hidden_master_string_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == HIDDEN_MASTER_STRING_LITERAL


def test_resolve_hidden_master_string_vn_returns_resolved_value_when_available():
    fake_profile = CatalogProfile(workspace_id=704, catalog_prefix="", cpq_models=("APX1000",))
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product", return_value=fake_profile),
        patch(
            "aryx.cpq.catalog_profile.resolve_variable_name_for_role",
            return_value="realHiddenMsVarName_astro",
        ),
    ):
        assert resolve_hidden_master_string_vn(
            {"productSelectionProduct_all": "X"}, 704,
        ) == "realHiddenMsVarName_astro"


def test_resolve_hidden_master_string_vn_uses_product_and_workspace_from_filled():
    with (
        _enabled_settings(),
        patch("aryx.cpq.catalog_profile.CatalogProfile.for_product") as mock_for_product,
    ):
        mock_for_product.return_value.resolved_vn_or.return_value = HIDDEN_MASTER_STRING_LITERAL
        resolve_hidden_master_string_vn(
            {"productSelectionProduct_all": "APX NEXT XE"}, 704, "Astro", {"k": "v"},
        )
    mock_for_product.assert_called_once_with("APX NEXT XE", 704, "Astro", {"k": "v"})
