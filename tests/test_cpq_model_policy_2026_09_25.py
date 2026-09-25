"""Tests for model_policy.py -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md's
T6 Phase 3 pilot slice (the "legacy" arm of the proposed ModelPolicy
design, proven standalone before any real call site is touched).
"""
from __future__ import annotations

from aryx.cpq.model_policy import (
    duplicate_display_name_canonical_item_value,
    optional_empty_fill_accepted_vns,
)
from aryx.cpq.opt_out_and_duplicates import (
    _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE,
    _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS,
)


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
