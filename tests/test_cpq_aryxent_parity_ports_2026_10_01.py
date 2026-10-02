"""Flag-gated ports of already-fixed aryxent hardcoding fixes into dev_oci
(docs: aryx-oci_bug_cpq-parity-and-hardcoding.md D6, D14, D15, D3/D12).
Every flag is off by default and must leave behaviour unchanged when off.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.base_model_placeholder import is_base_model_placeholder
from aryx.cpq.bml.bml_branches import _split_pipe_caret_values
from aryx.cpq.data_table_bridge import candidates as cand
from aryx.cpq.data_table_bridge import conflicts as conf

DEFAULT = cand._DEFAULT_CPQ_MODEL_CANDIDATES


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


# ---- D14: BML '~' split ----
def test_tilde_not_split_when_flag_off():
    with patch("aryx.cpq.bml.bml_branches.get_settings", _cfg(cpq_bml_tilde_split_enabled=False)):
        assert _split_pipe_caret_values(["A~B~C"]) == ["A~B~C"]
        assert _split_pipe_caret_values(["A|^|B"]) == ["A", "B"]


def test_tilde_split_when_flag_on():
    with patch("aryx.cpq.bml.bml_branches.get_settings", _cfg(cpq_bml_tilde_split_enabled=True)):
        assert _split_pipe_caret_values(["A~B~C"]) == ["A", "B", "C"]
        assert _split_pipe_caret_values(["A|^|B~C", "D"]) == ["A", "B", "C", "D"]


# ---- D6: '*' placeholder guard ----
def test_placeholder_guard_off_accepts_star():
    with patch("aryx.cpq.base_model_placeholder.get_settings", _cfg(cpq_base_model_placeholder_guard_enabled=False)):
        assert not is_base_model_placeholder("modelSelectionbaseModel_astro", "*")


def test_placeholder_guard_on_rejects_star_only_for_base_model():
    with patch("aryx.cpq.base_model_placeholder.get_settings", _cfg(cpq_base_model_placeholder_guard_enabled=True)):
        assert is_base_model_placeholder("modelSelectionbaseModel_astro", "*")
        assert not is_base_model_placeholder("modelSelectionbaseModel_astro", "H92UCH9PW7AN")
        assert not is_base_model_placeholder("someOther_astro", "*")


# ---- D15: generic pair exclusion ----
def test_generic_exclusion_helper():
    cands = ("APXNEXT", "APXNEXT_BOM", "REAL1")
    with patch("aryx.cpq.data_table_bridge.conflicts.get_settings", _cfg(cpq_generic_candidate_exclusion_enabled=False)):
        assert conf._without_generic_non_primary(cands) == cands
    with patch("aryx.cpq.data_table_bridge.conflicts.get_settings", _cfg(cpq_generic_candidate_exclusion_enabled=True)):
        # first position is kept (primary); later generic members dropped
        assert conf._without_generic_non_primary(cands) == ("APXNEXT", "REAL1")
        assert conf._without_generic_non_primary(("REAL1", "APXNEXT", "APXNEXT_BOM")) == ("REAL1",)


# ---- D3/D12: real models before the generic fallback ----
def _run(flag):
    cfg = _cfg(
        data_table_candidates_empty_on_no_match_enabled=False,
        cpq_candidates_real_models_first_enabled=flag,
    )
    with (
        patch("aryx.cpq.data_table_bridge.candidates.get_settings", cfg),
        patch("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows", return_value=None),
        patch("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_model_family", return_value=None),
        patch("aryx.cpq.data_table_bridge.candidates.dt_discover_cpq_models_for_base_model", return_value=("REAL1",)),
    ):
        return cand._cpq_model_candidates("p", 1, "", None, base_model="BM")


def test_candidate_order_unchanged_when_flag_off():
    assert _run(False) == DEFAULT + ("REAL1",)


def test_real_models_first_when_flag_on():
    assert _run(True) == ("REAL1",) + DEFAULT
