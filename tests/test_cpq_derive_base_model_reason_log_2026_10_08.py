"""Diagnostic only: when the base model is not derived, one DEBUG line says why (ws 1267, APX 900: "Since we locked in
United States, please choose the Base Model", 660 options, and nothing in the logs said why the derivation did nothing)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq import derive_base_model_pick as pick
from aryx.cpq.data_table import data_table_derive_base_model as ddb

OPTIONS = [SimpleNamespace(item_value="H92UCF9PW6AN", display_name="a"), SimpleNamespace(item_value="H92KDF9PW6AN", display_name="b")]
CANDIDATES = "aryx.cpq.derive_base_model_pick.resolved_model_first_candidates"
DERIVE = "aryx.cpq.derive_base_model_pick.derive_base_model_from_known_attrs"
COUNT = "aryx.cpq.derive_base_model_pick.model_base_models"


def _run(filled=None, candidates=(), derived=None, debug=True, flag=True, cache=None, options=OPTIONS,
         base_models=frozenset({"x", "y", "z"})):
    out = []
    settings = SimpleNamespace(cpq_derive_base_model_enabled=flag)
    with patch.object(pick, "get_settings", return_value=settings), \
            patch.object(pick, "would_log", return_value=debug), \
            patch.object(pick, "raven_log", side_effect=lambda *a, **k: out.append((a[2], k.get("context", {})))), \
            patch(CANDIDATES, return_value=list(candidates)), patch(DERIVE, return_value=derived), \
            patch(COUNT, return_value=set(base_models)):
        result = pick.derived_base_model_option(options, filled if filled is not None else {}, 1267, "p", cache)
    return result, out


def _not_derived(out):
    return [c for m, c in out if m.startswith("ask.base_model.not_derived")]


def test_a_blank_product_with_no_resolved_model_is_named():
    result, out = _run(filled={})
    (ctx,) = _not_derived(out)
    assert result is None and ctx["reason_code"] == "NO_CANDIDATE_MODEL_PRODUCT_BLANK" and ctx["product_filled"] is False


def test_a_filled_product_with_no_candidate_is_named():
    _, out = _run(filled={"productSelectionProduct_all": "APX 900"})
    assert _not_derived(out)[0]["reason_code"] == "NO_CANDIDATE_MODEL"


def test_candidates_that_do_not_narrow_to_one_report_their_base_model_counts():
    result, out = _run(filled={"productSelectionProduct_all": "APX 900", "a": "v"}, candidates=["APX900"], derived=None)
    ctx = _not_derived(out)[0]
    assert result is None and ctx["reason_code"] == "NOT_NARROWED_TO_ONE"
    assert ctx["candidates"] == ["APX900"] and ctx["base_models_per_candidate"] == {"APX900": 3}
    assert ctx["known_attr_count"] == 2 and ctx["option_count"] == 2


def test_a_derived_code_that_is_not_an_option_is_named():
    result, out = _run(candidates=["APX900"], derived="NOT-AN-OPTION")
    assert result is None and _not_derived(out)[0]["reason_code"] == "DERIVED_CODE_NOT_AN_OPTION"


def test_a_successful_derivation_returns_the_option_and_logs_no_not_derived_line():
    result, out = _run(candidates=["APX900"], derived="H92UCF9PW6AN")
    assert result is OPTIONS[0] and _not_derived(out) == []
    assert any(m.startswith("ask.base_model.derived") for m, _ in out)


def test_logged_once_per_cache():
    cache: dict = {}
    _, out1 = _run(cache=cache)
    _, out2 = _run(cache=cache)
    assert len(_not_derived(out1)) == 1 and _not_derived(out2) == []


def test_with_debug_off_nothing_is_logged_and_the_result_is_the_same():
    result, out = _run(debug=False)
    assert result is None and _not_derived(out) == []


def test_flag_off_or_no_options_returns_none_without_resolving_anything():
    for kwargs in ({"flag": False}, {"options": []}):
        with patch(CANDIDATES) as cand, patch(DERIVE) as derive:
            out = []
            settings = SimpleNamespace(cpq_derive_base_model_enabled=kwargs.get("flag", True))
            with patch.object(pick, "get_settings", return_value=settings),                     patch.object(pick, "raven_log", side_effect=lambda *a, **k: out.append(a)):
                result = pick.derived_base_model_option(kwargs.get("options", OPTIONS), {}, 1267, "p", None)
        assert result is None and out == []
        cand.assert_not_called()
        derive.assert_not_called()


def test_a_changed_outcome_in_a_later_pass_is_logged_but_an_identical_repeat_is_not():
    """Pass 0 has no product (nothing to resolve); a later pass has the product and a candidate that still does not
    narrow. The second must not be hidden by the first, and repeating the second must stay quiet."""
    cache: dict = {}
    _, first = _run(filled={}, cache=cache)
    _, second = _run(filled={"productSelectionProduct_all": "APX 900"}, candidates=["APX900"], cache=cache)
    _, repeat = _run(filled={"productSelectionProduct_all": "APX 900"}, candidates=["APX900"], cache=cache)
    assert [c["reason_code"] for c in _not_derived(first)] == ["NO_CANDIDATE_MODEL_PRODUCT_BLANK"]
    assert [c["reason_code"] for c in _not_derived(second)] == ["NOT_NARROWED_TO_ONE"]
    assert _not_derived(repeat) == []


def test_a_model_with_no_constraint_rows_is_named():
    _, out = _run(candidates=["APXFOO"], base_models=frozenset())
    ctx = _not_derived(out)[0]
    assert ctx["reason_code"] == "NO_BASE_MODEL_ROWS" and ctx["base_models_per_candidate"] == {"APXFOO": 0}


def test_with_several_candidates_the_reason_describes_the_last_one_that_produced_a_code():
    results = {"A": "NOT-AN-OPTION", "B": None}
    out = []
    with patch.object(pick, "get_settings", return_value=SimpleNamespace(cpq_derive_base_model_enabled=True)),             patch.object(pick, "would_log", return_value=True),             patch.object(pick, "raven_log", side_effect=lambda *a, **k: out.append((a[2], k.get("context", {})))),             patch(CANDIDATES, return_value=["A", "B"]), patch(COUNT, return_value={"x"}),             patch(DERIVE, side_effect=lambda m, *a, **k: results[m]):
        assert pick.derived_base_model_option(OPTIONS, {}, 1267, "p", None) is None
    ctx = _not_derived(out)[0]
    assert ctx["reason_code"] == "DERIVED_CODE_NOT_AN_OPTION" and ctx["results"] == results


def test_a_failing_diagnostic_never_breaks_the_fill_and_leaves_a_debug_trace(caplog):
    import logging
    with patch.object(pick, "would_log", return_value=True),             patch.object(pick, "get_settings", return_value=SimpleNamespace(cpq_derive_base_model_enabled=True)),             patch.object(pick, "raven_log", side_effect=RuntimeError("boom")),             patch(CANDIDATES, return_value=[]), caplog.at_level(logging.DEBUG, logger=pick.logger.name):
        assert pick.derived_base_model_option(OPTIONS, {}, 1267, "p", None) is None
    assert "not_derived diagnostic failed" in caplog.text


# --- the data-table helpers the diagnostic and the derivation share -----------------------------------------------
ROWS = [{"CPQModel": "APX900", "BaseModel": "H92UCF9PW6AN"}, {"CPQModel": "apx900", "BaseModel": "H92KDF9PW6AN"},
        {"CPQModel": "APX900", "BaseModel": "ALL"}, {"CPQModel": "APX900", "BaseModel": ""},
        {"CPQModel": "APX3000", "BaseModel": "X"}]


def test_model_base_models_excludes_blank_and_all_and_other_models():
    with patch.object(ddb, "_load_all_tables", return_value=(ROWS, [], [], [], [])):
        assert ddb.model_base_models("apx900", 1267) == {"H92UCF9PW6AN", "H92KDF9PW6AN"}
        assert ddb.model_base_models("", 1267) == set()


def test_the_derivation_itself_is_unchanged_by_the_refactor():
    rows = [{"CPQModel": "APXN30", "BaseModel": "A", "attr1": "freq", "val1": "VHF"},
            {"CPQModel": "APXN30", "BaseModel": "B", "attr1": "freq", "val1": "UHF"}]
    with patch.object(ddb, "_load_all_tables", return_value=(rows, [], [], [], [])):
        assert ddb.derive_base_model_from_known_attrs("APXN30", {"freq": "vhf"}, 1267) == "A"
        assert ddb.derive_base_model_from_known_attrs("APXN30", {}, 1267) is None
        assert ddb.derive_base_model_from_known_attrs("NOPE", {"freq": "VHF"}, 1267) is None
