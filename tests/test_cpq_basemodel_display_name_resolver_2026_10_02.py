"""Port of dev-rv-msi #341: resolve a customer's free-text device mention
via the Basemodeltoconfig displayModel -> cpqModel table, gated behind
``cpq_basemodel_display_name_resolution_enabled`` (default off).

#341's tests are retargeted to dev_oci's split layout (the loader is the
shape-detected `data_table_inference._load_basemodel_to_config_rows`).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq.data_table import data_table_cache, data_table_inference, data_table_loader
from aryx.cpq.data_table.data_table_resolver import (
    resolve_cpq_model_from_display_name,
    resolve_product_cpq_models_from_hint,
)


@pytest.fixture(autouse=True)
def _flag_and_caches():
    s = get_settings()
    prev = s.cpq_basemodel_display_name_resolution_enabled
    data_table_loader._clear_tables_cache()
    yield
    s.cpq_basemodel_display_name_resolution_enabled = prev
    data_table_loader._clear_tables_cache()


@pytest.fixture
def flag_on():
    get_settings().cpq_basemodel_display_name_resolution_enabled = True


def _row(display_model: str, cpq_model: str, base_model: str) -> dict:
    return {"displayModel": display_model, "cpqModel": cpq_model, "baseModel": base_model}


# Real data shape from dev-rv-msi #341 (workspace 97, 2026-09-21).
_REAL_ROWS = [
    _row("APX 900", "APX900", "H92UCF9PW6AN"),
    _row("APX 900", "APX900", "H92QDH9PW7AN"),
    _row("APX 3000", "APX3000", "H59UCD9PW4AN"),
    _row("APX 3000 FLASHPORT", "APX3000FLASHPORT", "T7991A"),
    # The anomalous no-space row: different cpqModel.
    _row("APX3000", "TXM3000", "T05TSS9PW1AN"),
]


@pytest.fixture
def rows_patch():
    def _patch(rows):
        return patch.object(
            data_table_inference, "_load_basemodel_to_config_rows",
            return_value=rows,
        )
    return _patch


def test_resolves_apx_900(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        assert resolve_cpq_model_from_display_name(
            "I want APX 900 for United States", 97, "Astro25Configdata") == ("APX900",)


def test_spaced_apx_3000_never_hits_anomalous_row(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        result = resolve_cpq_model_from_display_name("I want APX 3000 for United States", 97)
    assert result == ("APX3000",)


def test_flashport_superstring_resolves_to_more_specific(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        result = resolve_cpq_model_from_display_name("I want the APX 3000 FLASHPORT for US", 97)
    assert result == ("APX3000FLASHPORT",)


def test_unrelated_matches_refuse_to_guess(flag_on, rows_patch):
    rows = _REAL_ROWS + [_row("MTR 3000", "MTR3000", "T3000A")]
    with rows_patch(rows):
        assert resolve_cpq_model_from_display_name(
            "compare APX 3000 against MTR 3000 for United States", 97) == ()


def test_no_space_form_hits_the_anomalous_row_as_data_says(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        assert resolve_cpq_model_from_display_name("I want APX3000 for US", 97) == ("TXM3000",)


def test_empty_when_no_table(flag_on, rows_patch):
    with rows_patch([]):
        assert resolve_cpq_model_from_display_name("I want APX 900 for US", 97) == ()


def test_empty_for_unresolvable_text(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        assert resolve_cpq_model_from_display_name("I need a quote for some radios", 97) == ()


def test_min_length_guard_ignores_short_display_model(flag_on, rows_patch):
    with rows_patch([_row("US", "USMODEL", "B1")]):
        assert resolve_cpq_model_from_display_name("quote for US please", 97) == ()


def test_hint_resolver_prefers_display_name_table_when_flag_on(flag_on, rows_patch):
    with rows_patch(_REAL_ROWS):
        assert resolve_product_cpq_models_from_hint("I want APX 900 for US", 97) == ("APX900",)


def test_hint_resolver_falls_back_to_constraint_scan_when_no_display_match(flag_on, rows_patch):
    constraint = [{"CPQModel": "XYZ1", "attr1": "productSelectionProduct_all", "val1": "WIDGET ONE"}]
    tables = (constraint, [], [], [], [])
    with rows_patch(_REAL_ROWS), \
            patch("aryx.cpq.data_table.data_table_product._load_all_tables", return_value=tables):
        assert resolve_product_cpq_models_from_hint("I want WIDGET ONE please", 97) == ("XYZ1",)


def test_flag_off_never_consults_display_name_table(rows_patch):
    constraint = [{"CPQModel": "XYZ1", "attr1": "productSelectionProduct_all", "val1": "APX 900"}]
    tables = (constraint, [], [], [], [])
    with rows_patch(_REAL_ROWS) as loader, \
            patch("aryx.cpq.data_table.data_table_product._load_all_tables", return_value=tables):
        # Flag off: constraint-row scan result, display table untouched.
        assert resolve_product_cpq_models_from_hint("I want APX 900 for US", 97) == ("XYZ1",)
    loader.assert_not_called()


def test_real_loader_shape_detects_rows_via_fake_rdb(flag_on):
    class _Rdb:
        def fetch_all_entities_grouped_by_type(self, workspace_id):
            return {
                "Basemodeltoconfig": [(i, r) for i, r in enumerate(_REAL_ROWS, start=1)],
                "Whitelist": [(99, {"BaseModel": "B1", "attr1": "a", "val1": "b"})],
            }

    with patch.object(data_table_loader, "get_cpq_rdb", lambda: _Rdb()), \
            patch.object(data_table_cache, "_current_invalidation_marker", return_value=None):
        assert resolve_cpq_model_from_display_name("I want APX 900 for US", 97) == ("APX900",)
