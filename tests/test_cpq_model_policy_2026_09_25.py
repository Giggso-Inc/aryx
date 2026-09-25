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
from aryx.cpq.model_policy import (
    duplicate_display_name_canonical_item_value,
    optional_empty_fill_accepted_vns,
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


def test_optional_empty_wiring_not_called_when_flag_disabled():
    attr = _attr("promoApplicationServices_astro")
    state = AttrResolution(vn=attr.variable_name)
    with (
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.shadow_check_optional_empty_fill_vns",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.model_policy_shadow_check_enabled = False
        try_multi_optional_empty(MagicMock(), attr, _ctx(), _scope(), state)
    mock_shadow.assert_not_called()


def test_optional_empty_wiring_called_when_flag_enabled():
    attr = _attr("promoApplicationServices_astro")
    state = AttrResolution(vn=attr.variable_name, allowed_for_attr=None)
    with (
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.shadow_check_optional_empty_fill_vns",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.model_policy_shadow_check_enabled = True
        result = try_multi_optional_empty(MagicMock(), attr, _ctx(), _scope(), state)
    mock_shadow.assert_called_once_with(
        "promoApplicationServices_astro", True, "APX NEXT XE", 704, "Astro", {},
    )
    # The real fill decision is completely unaffected by the shadow check.
    assert result is True


def test_optional_empty_wiring_not_called_for_a_single_select_attr():
    """Even with the flag on, a non-multi attr must never trigger the
    shadow check -- it only runs inside the same guard the real branch
    uses (select_type=='multi' and not required and not a grid selector)."""
    attr = ConfigAttr(
        entity_id=1, variable_name="someSingleSelect_astro", display_label="x",
        required=False, default_value="", select_type="single", options=[],
    )
    state = AttrResolution(vn=attr.variable_name)
    with (
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.get_settings",
        ) as mock_cfg,
        patch(
            "aryx.cpq.auto_fill_stages.multi_optout_and_empty.shadow_check_optional_empty_fill_vns",
        ) as mock_shadow,
    ):
        mock_cfg.return_value.model_policy_shadow_check_enabled = True
        try_multi_optional_empty(MagicMock(), attr, _ctx(), _scope(), state)
    mock_shadow.assert_not_called()
