"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md Phase 4, Group 3 (T2): gates
_cpq_model_candidates' hardcoded APX NEXT fallback behind
data_table_candidates_empty_on_no_match_enabled -- off by default
(byte-identical to before this flag existed), returns an empty tuple
plus a logged data gap instead of guessing APX NEXT when on.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from aryx.cpq.data_table_bridge.candidates import (
    _DEFAULT_CPQ_MODEL_CANDIDATES,
    _cpq_model_candidates,
)


def _enabled_settings():
    mock_cfg = MagicMock()
    mock_cfg.return_value.data_table_candidates_empty_on_no_match_enabled = True
    return patch("aryx.cpq.data_table_bridge.candidates.get_settings", mock_cfg)


def _disabled_settings():
    mock_cfg = MagicMock()
    mock_cfg.return_value.data_table_candidates_empty_on_no_match_enabled = False
    return patch("aryx.cpq.data_table_bridge.candidates.get_settings", mock_cfg)


def test_no_match_returns_the_legacy_default_at_real_gate_off():
    with (
        _disabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family",
            return_value=None,
        ),
    ):
        result = _cpq_model_candidates("Some Unmapped Product", workspace_id=704)
    assert result == _DEFAULT_CPQ_MODEL_CANDIDATES


def test_no_workspace_id_returns_the_legacy_default_at_real_gate_off():
    """workspace_id=None never even reaches the row/family resolution
    calls -- confirm the fallback still applies identically."""
    result = _cpq_model_candidates("Some Unmapped Product", workspace_id=None)
    assert result == _DEFAULT_CPQ_MODEL_CANDIDATES


def test_no_match_returns_empty_when_gate_is_on():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family",
            return_value=None,
        ),
    ):
        result = _cpq_model_candidates("Some Unmapped Product", workspace_id=704)
    assert result == ()


def test_no_match_logs_a_data_gap_warning_when_gate_is_on(caplog):
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family",
            return_value=None,
        ),
        caplog.at_level(logging.WARNING, logger="aryx.cpq.data_table_bridge.candidates"),
    ):
        _cpq_model_candidates("Some Unmapped Product", workspace_id=704, catalog_prefix="Astro")
    assert any(
        "no real CPQModel candidates resolved" in r.message for r in caplog.records
    )


def test_a_real_row_level_match_is_unaffected_by_the_gate():
    """The gate only touches the "nothing resolved at all" fallback --
    a genuine row-level match must return unchanged regardless of the
    flag's state."""
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=("REALMODEL",),
        ),
    ):
        result = _cpq_model_candidates("A Real Product", workspace_id=704)
    assert result == ("REALMODEL",)


def test_a_real_family_level_match_is_unaffected_by_the_gate():
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family",
            return_value="REALFAMILY",
        ),
    ):
        result = _cpq_model_candidates("A Real Product", workspace_id=704)
    assert result == ("REALFAMILY", "REALFAMILY_BOM")


def test_base_model_discovery_still_appends_onto_an_empty_primary_when_gate_on():
    """`base_model` appends discovered CPQModel codes AFTER whichever
    primary resolution already ran -- confirm this still works when
    primary resolved to an empty tuple (gate on, no match)."""
    with (
        _enabled_settings(),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family",
            return_value=None,
        ),
        patch(
            "aryx.cpq.data_table_bridge.candidates.dt_discover_cpq_models_for_base_model",
            return_value=("DISCOVERED",),
        ),
    ):
        result = _cpq_model_candidates(
            "Some Unmapped Product", workspace_id=704, base_model="SOMEBASEMODEL",
        )
    assert result == ("DISCOVERED",)
