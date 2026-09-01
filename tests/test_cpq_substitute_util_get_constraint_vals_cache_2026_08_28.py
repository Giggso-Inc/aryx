"""Live-confirmed gap (2026-08-28, P5 follow-up to the P2 fix in
tests/test_cpq_data_table_forced_vns_cache_2026_08_28.py): `_substitute_
util_get_constraint_vals` has no memoization of its own. It is called once
per script-backed ConstraintRule inside `apply_constraint_rules` -- whose
OWN whole-function cache (`_constraint_cache`, RC6) only skips this work
when NOTHING relevant changed since the last pass. On a genuine cache-miss
(a real narrowing/resync), this function still independently re-walks the
full `_cpq_model_candidates` cross-product for every script-backed rule --
confirmed live this alone cost 82s/59s/37s across 3 real APX Next passes
before `_constraint_cache` stabilized (engine.py's own comment at its
second call site).

Fix: `_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE`, keyed on the FULL
`filled`-state signature (via the same `_fill_signature` helper already
used elsewhere in this file for this exact class of problem) -- not just
base_model/product, because `resolve_whitelist_values`' own multi-
condition row matching can depend on any filled attribute.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import (
    _clear_substitute_util_get_constraint_vals_cache,
    _substitute_util_get_constraint_vals,
)

_SCRIPT = (
    'params.put(inputParam, "Attribute Variable Name", "someAttrVarName_astro");\n'
    "returnVal = util.getConstraintVals(dictVar, listVar);"
)


def setup_function(_fn):
    _clear_substitute_util_get_constraint_vals_cache()


def teardown_function(_fn):
    _clear_substitute_util_get_constraint_vals_cache()


def test_second_call_with_identical_inputs_skips_recomputation():
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["A", "B"],
    ):
        first = _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        assert mock_cands.call_count == 1

        second = _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        assert mock_cands.call_count == 1, (
            "the expensive candidate-resolution call must not run again -- "
            "the cache should have short-circuited before reaching it"
        )
        assert first == second
        assert "util.getConstraintVals" not in first


def test_changed_unrelated_filled_value_correctly_misses_the_cache():
    """resolve_whitelist_values' own multi-condition row matching can
    depend on ANY filled attribute, not just base_model/product -- a
    narrower cache key would risk silently reusing a stale substitution
    for a row whose OTHER condition column just changed. This proves the
    cache key is broad enough to catch that."""
    base_filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["A", "B"],
    ):
        _substitute_util_get_constraint_vals(
            _SCRIPT, {**base_filled, "someUnrelatedAttr_astro": "X"}, 93, "", None,
        )
        _substitute_util_get_constraint_vals(
            _SCRIPT, {**base_filled, "someUnrelatedAttr_astro": "Y"}, 93, "", None,
        )
        assert mock_cands.call_count == 2, (
            "a change to ANY filled attribute must miss the cache -- "
            "resolve_whitelist_values can depend on attributes beyond "
            "base_model/product"
        )


def test_different_script_correctly_misses_the_cache():
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    other_script = (
        'params.put(inputParam, "Attribute Variable Name", "aDifferentAttr_astro");\n'
        "returnVal = util.getConstraintVals(dictVar, listVar);"
    )
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["A", "B"],
    ):
        _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        _substitute_util_get_constraint_vals(other_script, filled, 93, "", None)
        assert mock_cands.call_count == 2


def test_different_workspace_correctly_misses_the_cache():
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["A", "B"],
    ):
        _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        _substitute_util_get_constraint_vals(_SCRIPT, filled, 39005, "", None)
        assert mock_cands.call_count == 2


def test_no_ingested_rows_still_caches_the_unchanged_fallback():
    """The `None` (no rows at all) case leaves the script unchanged -- must
    still be cached, not just the substituted-success case."""
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ) as mock_cands, patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values", return_value=None,
    ):
        first = _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        second = _substitute_util_get_constraint_vals(_SCRIPT, filled, 93, "", None)
        assert first == second == _SCRIPT, "no ingested rows -- script must pass through unchanged"
        assert mock_cands.call_count == 1
