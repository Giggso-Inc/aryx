"""Live-confirmed gap (2026-08-28): `_data_table_forced_vns` has no cache
parameter at any of its 4 real call sites (`build_payload` never threads
one through), so every call re-ran its full `_ATTRSEQ_CONFIRMED_REQUIRED_
VNS` x candidate-CPQ-models cross-product from scratch -- 3,580 such
lookups logged within a single real APX Next Product-selection turn
(elapsed_s=177.75 for that turn's rule-eval step alone).

Fix: `_DATA_TABLE_FORCED_VNS_CACHE`, a module-level short-TTL cache keyed
on exactly the inputs the function reads (workspace/catalog/base_model/
product plus each `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` member's own filled/
filled_multi value) -- a real change to any of those inputs naturally
misses and recomputes.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine, _clear_data_table_forced_vns_cache


def setup_function(_fn):
    _clear_data_table_forced_vns_cache()


def teardown_function(_fn):
    _clear_data_table_forced_vns_cache()


def test_second_call_with_identical_inputs_skips_recomputation():
    """The nested cross-product loop must not re-run when nothing the
    function reads has changed -- the whole point of the cache."""
    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
        "wirelessCarrier_astro": "ATT/FIRSTNET",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        first = engine._data_table_forced_vns(filled, 93, "")
        assert mock_cands.call_count == 1

        second = engine._data_table_forced_vns(filled, 93, "")
        # The expensive candidate-resolution call must NOT run again --
        # the cache should have short-circuited before reaching it.
        assert mock_cands.call_count == 1
        assert second == first == frozenset({"wirelessCarrier_astro"})


def test_changed_filled_value_correctly_misses_the_cache():
    """A real change to a tracked input (the carrier value itself) must
    never be masked by a stale cache hit."""
    engine = CpqEngine()
    base_filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        legal_result = engine._data_table_forced_vns(
            {**base_filled, "wirelessCarrier_astro": "ATT/FIRSTNET"}, 93, "",
        )
        illegal_result = engine._data_table_forced_vns(
            {**base_filled, "wirelessCarrier_astro": "SOME MADE UP VALUE"}, 93, "",
        )
        assert mock_cands.call_count == 2
        assert legal_result == frozenset({"wirelessCarrier_astro"})
        assert illegal_result == frozenset()


def test_different_workspace_correctly_misses_the_cache():
    """Two different workspaces must never share a cached result even
    with identical filled state -- catalogs differ per workspace."""
    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
        "wirelessCarrier_astro": "ATT/FIRSTNET",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        engine._data_table_forced_vns(filled, 93, "")
        engine._data_table_forced_vns(filled, 39005, "")
        assert mock_cands.call_count == 2


def test_multiselect_value_change_correctly_misses_the_cache():
    """filled_multi-sourced members must also be part of the cache key --
    not just the plain `filled` dict."""
    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
        "productSelectionProduct_all": "APX NEXT ENHANCED",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        r1 = engine._data_table_forced_vns(
            filled, 93, "",
            filled_multi={"carrierSelectionMultiSelect_astro": ["ATT/FIRSTNET"]},
        )
        r2 = engine._data_table_forced_vns(
            filled, 93, "",
            filled_multi={"carrierSelectionMultiSelect_astro": ["ATT/FIRSTNET", "SOME MADE UP VALUE"]},
        )
        assert mock_cands.call_count == 2
        assert r1 == frozenset({"carrierSelectionMultiSelect_astro"})
        assert r2 == frozenset()
