"""Diagnostic only: when the base model is not derived, one DEBUG line says why.

ws 1267, APX 900: "Since we locked in United States, please choose the Base Model" (660 options), and nothing in the
logs said why the derivation did nothing. The line carries the reason, the candidate models and, per known attribute,
what it did to the remaining base models. It never changes the fill and never contains customer text."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq import derive_base_model_pick as pick
from aryx.cpq.data_table import data_table_derive_base_model as ddb

OPTIONS = [
    SimpleNamespace(item_value="H92UCF9PW6AN", display_name="a"),
    SimpleNamespace(item_value="H92KDF9PW6AN", display_name="b"),
]
CANDIDATES = "aryx.cpq.derive_base_model_pick.resolved_model_first_candidates"
DERIVE = "aryx.cpq.derive_base_model_pick.derive_base_model_from_known_attrs"
COUNT = "aryx.cpq.derive_base_model_pick.model_base_models"
EXPLAIN = "aryx.cpq.derive_base_model_pick.explain_known_attrs"
PRODUCT = {"productSelectionProduct_all": "APX 900"}


def _run(filled=None, candidates=(), derived=None, debug=True, flag=True, cache=None, options=OPTIONS,
         base_models=frozenset({"x", "y", "z"}), explain=None, sources=None):
    out = []
    settings = SimpleNamespace(cpq_derive_base_model_enabled=flag)
    with patch.object(pick, "get_settings", return_value=settings), \
            patch.object(pick, "would_log", return_value=debug), \
            patch.object(pick, "raven_log",
                         side_effect=lambda *a, **k: out.append((a[2], k.get("context", {})))), \
            patch(CANDIDATES, return_value=list(candidates)), patch(DERIVE, return_value=derived), \
            patch(COUNT, return_value=set(base_models)), \
            patch(EXPLAIN, side_effect=explain or (lambda *a, **k: [])):
        result = pick.derived_base_model_option(
            options, filled if filled is not None else {}, 1267, "p", cache, sources=sources)
    return result, out


def _not_derived(out):
    return [c for m, c in out if m.startswith("ask.base_model.not_derived")]


def test_a_blank_product_with_no_resolved_model_is_named():
    result, out = _run(filled={})
    (ctx,) = _not_derived(out)
    assert result is None and ctx["product_filled"] is False
    assert ctx["reason_code"] == "NO_CANDIDATE_MODEL_PRODUCT_BLANK"


def test_a_filled_product_with_no_candidate_is_named():
    _, out = _run(filled=PRODUCT)
    assert _not_derived(out)[0]["reason_code"] == "NO_CANDIDATE_MODEL"


def test_candidates_that_do_not_narrow_to_one_report_their_base_model_counts():
    result, out = _run(filled={**PRODUCT, "a": "v"}, candidates=["APX900"], derived=None)
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


def test_an_identical_repeat_is_logged_once_per_cache():
    cache: dict = {}
    _, out1 = _run(cache=cache)
    _, out2 = _run(cache=cache)
    assert len(_not_derived(out1)) == 1 and _not_derived(out2) == []


def test_with_debug_off_nothing_is_logged_and_the_result_is_the_same():
    result, out = _run(debug=False)
    assert result is None and _not_derived(out) == []


def test_flag_off_or_no_options_returns_none_without_resolving_anything():
    for kwargs in ({"flag": False}, {"options": []}):
        out = []
        settings = SimpleNamespace(cpq_derive_base_model_enabled=kwargs.get("flag", True))
        with patch(CANDIDATES) as cand, patch(DERIVE) as derive, \
                patch.object(pick, "get_settings", return_value=settings), \
                patch.object(pick, "raven_log", side_effect=lambda *a, **k: out.append(a)):
            result = pick.derived_base_model_option(kwargs.get("options", OPTIONS), {}, 1267, "p", None)
        assert result is None and out == []
        cand.assert_not_called()
        derive.assert_not_called()


def test_a_changed_outcome_in_a_later_pass_is_logged_but_an_identical_repeat_is_not():
    """Pass 0 has no product (nothing to resolve); a later pass has the product and a candidate that still does not
    narrow. The second must not be hidden by the first, and repeating the second must stay quiet."""
    cache: dict = {}
    _, first = _run(filled={}, cache=cache)
    _, second = _run(filled=PRODUCT, candidates=["APX900"], cache=cache)
    _, repeat = _run(filled=PRODUCT, candidates=["APX900"], cache=cache)
    assert [c["reason_code"] for c in _not_derived(first)] == ["NO_CANDIDATE_MODEL_PRODUCT_BLANK"]
    assert [c["reason_code"] for c in _not_derived(second)] == ["NOT_NARROWED_TO_ONE"]
    assert _not_derived(repeat) == []


def test_a_later_pass_with_the_same_reason_but_more_known_attributes_is_logged_too():
    """Same reason, same candidates, but the frequency band is known in the second pass: `known_attr_match` differs,
    so it must not be dropped as a repeat of the first."""
    cache: dict = {}
    first_filled = {**PRODUCT, "country_astro": "US"}
    second_filled = {**first_filled, "modelSelectionFrequencyBands_astro": "VHF"}
    _, first = _run(filled=first_filled, candidates=["APX900"], cache=cache)
    _, second = _run(filled=second_filled, candidates=["APX900"], cache=cache)
    _, repeat = _run(filled=second_filled, candidates=["APX900"], cache=cache)
    assert len(_not_derived(first)) == 1 and len(_not_derived(second)) == 1 and _not_derived(repeat) == []
    assert _not_derived(first)[0]["reason_code"] == _not_derived(second)[0]["reason_code"]


def test_blind_filled_attributes_do_not_make_a_pass_look_new():
    """A blind-filled value is not evidence, so changing only it is the same outcome."""
    cache: dict = {}
    sources = {"guess_astro": "blind_pick_rule_governed"}
    _, first = _run(filled={**PRODUCT}, candidates=["APX900"], cache=cache, sources=sources)
    _, second = _run(filled={**PRODUCT, "guess_astro": "x"}, candidates=["APX900"], cache=cache, sources=sources)
    assert len(_not_derived(first)) == 1 and _not_derived(second) == []
    assert _not_derived(first)[0]["blind_attr_count"] == 1


def test_a_model_with_no_constraint_rows_is_named():
    _, out = _run(candidates=["APXFOO"], base_models=frozenset())
    ctx = _not_derived(out)[0]
    assert ctx["reason_code"] == "NO_BASE_MODEL_ROWS" and ctx["base_models_per_candidate"] == {"APXFOO": 0}


def test_with_several_candidates_the_reason_describes_the_last_one_that_produced_a_code():
    results = {"A": "NOT-AN-OPTION", "B": None}
    out = []
    settings = SimpleNamespace(cpq_derive_base_model_enabled=True)
    with patch.object(pick, "get_settings", return_value=settings), \
            patch.object(pick, "would_log", return_value=True), \
            patch.object(pick, "raven_log",
                         side_effect=lambda *a, **k: out.append((a[2], k.get("context", {})))), \
            patch(CANDIDATES, return_value=["A", "B"]), patch(COUNT, return_value={"x"}), \
            patch(EXPLAIN, return_value=[]), \
            patch(DERIVE, side_effect=lambda m, *a, **k: results[m]):
        assert pick.derived_base_model_option(OPTIONS, {}, 1267, "p", None) is None
    ctx = _not_derived(out)[0]
    assert ctx["reason_code"] == "DERIVED_CODE_NOT_AN_OPTION" and ctx["results"] == results


def test_a_failing_diagnostic_never_breaks_the_fill_and_leaves_a_debug_trace(caplog):
    settings = SimpleNamespace(cpq_derive_base_model_enabled=True)
    with patch.object(pick, "would_log", return_value=True), \
            patch.object(pick, "get_settings", return_value=settings), \
            patch.object(pick, "raven_log", side_effect=RuntimeError("boom")), \
            patch(CANDIDATES, return_value=[]), patch(EXPLAIN, return_value=[]), \
            caplog.at_level(logging.DEBUG, logger=pick.logger.name):
        assert pick.derived_base_model_option(OPTIONS, {}, 1267, "p", None) is None
    assert "not_derived diagnostic failed" in caplog.text


def test_the_not_derived_line_carries_the_match_explanation_for_the_first_model_with_base_models():
    explained = [{"attr": "modelSelectionFrequencyBands_astro", "base_models_with_rows": 10,
                  "base_models_matching": 0}]
    asked = []
    _, out = _run(filled=PRODUCT, candidates=["APX900_BOM", "APX900"],
                  explain=lambda model, *a, **k: asked.append(model) or explained)
    assert _not_derived(out)[0]["known_attr_match"] == explained
    assert asked == ["APX900_BOM"]       # the patched count gives every candidate base models: the first wins


def test_a_model_without_base_models_is_not_explained():
    asked = []
    _, out = _run(candidates=["APXFOO"], base_models=frozenset(),
                  explain=lambda *a, **k: asked.append(a) or [])
    assert asked == [] and _not_derived(out)[0]["known_attr_match"] == []


# --- the data-table helpers the diagnostic and the derivation share -----------------------------------------------
ROWS = [
    {"CPQModel": "APX900", "BaseModel": "H92UCF9PW6AN"}, {"CPQModel": "apx900", "BaseModel": "H92KDF9PW6AN"},
    {"CPQModel": "APX900", "BaseModel": "ALL"}, {"CPQModel": "APX900", "BaseModel": ""},
    {"CPQModel": "APX3000", "BaseModel": "X"},
]


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


# --- explain_known_attrs: replays the derivation, names and counts only, never the known value ---------------------
FREQ, KEYPAD = "modelSelectionFrequencyBands_astro", "modelSelectionKeypadType_astro"
EXPLAIN_ROWS = [
    {"CPQModel": "APX900", "BaseModel": "A", "attr1": FREQ, "val1": "VHF", "attr2": KEYPAD, "val2": "FULL KEYPAD"},
    {"CPQModel": "APX900", "BaseModel": "B", "attr1": FREQ, "val1": "700/800 MHZ",
     "attr2": KEYPAD, "val2": "LIMITED KEYPAD"},
    {"CPQModel": "APX900", "BaseModel": "C", "attr1": FREQ, "val1": "UHF"},
    {"CPQModel": "APX900", "BaseModel": "D", "attr1": FREQ, "val1": ""},
    {"CPQModel": "APX900", "BaseModel": "ALL", "attr1": "other_astro", "val1": "x"},
]


def _explain(known, **kwargs):
    with patch.object(ddb, "_load_all_tables", return_value=(EXPLAIN_ROWS, [], [], [], [])):
        return ddb.explain_known_attrs("apx900", known, 1267, **kwargs)


def test_explain_reports_counts_and_row_values_but_never_the_known_value():
    secret = "ZZ-CUSTOMER-TEXT-4471"
    out = _explain({FREQ: "700-800 MHz", KEYPAD: secret, "untouched_astro": "v", "blank_astro": ""})
    by_attr = {e["attr"]: e for e in out}
    assert set(by_attr) == {FREQ, KEYPAD}
    freq = by_attr[FREQ]
    assert (freq["base_models_with_rows"], freq["base_models_matching"]) == (4, 0)
    assert freq["row_value_count"] == 3 and freq["row_values_sample"] == ["700/800 MHZ", "UHF", "VHF"]
    assert by_attr[KEYPAD]["base_models_matching"] == 0
    assert secret not in repr(out)


def test_explain_skips_blank_row_values():
    (freq,) = _explain({FREQ: "VHF"})
    assert "" not in freq["row_values_sample"] and freq["row_value_count"] == 3


def test_explain_matches_case_insensitively_like_the_derivation():
    (freq,) = _explain({FREQ: "vhf"})
    assert freq["base_models_matching"] == 1


def _by_attr(entries):
    return {e["attr"]: e for e in entries}


def test_explain_replays_the_intersection_in_the_order_the_derivation_applies_it():
    out = _by_attr(_explain({FREQ: "VHF", KEYPAD: "LIMITED KEYPAD"}))
    freq, keypad = out[FREQ], out[KEYPAD]
    assert (freq["applied_order"], freq["remaining_before"], freq["remaining_after"]) == (0, 4, 1)
    # A is the only frequency match; the keypad value matches B, which is no longer remaining: it is ignored
    assert (keypad["applied_order"], keypad["matching_among_remaining"]) == (1, 0)
    assert keypad["base_models_matching"] == 1 and keypad["remaining_before"] == keypad["remaining_after"] == 1


def test_explain_shows_that_the_other_order_gives_another_result():
    out = _by_attr(_explain({KEYPAD: "LIMITED KEYPAD", FREQ: "VHF"}))
    keypad, freq = out[KEYPAD], out[FREQ]
    assert (keypad["applied_order"], keypad["remaining_after"]) == (0, 3)       # B, plus C and D (no keypad rows)
    assert (freq["applied_order"], freq["matching_among_remaining"]) == (1, 0)  # VHF is A, already excluded
    assert freq["remaining_after"] == 3


def test_explain_puts_attributes_that_matched_nothing_remaining_first():
    out = _explain({FREQ: "VHF", KEYPAD: "LIMITED KEYPAD"})
    assert [e["attr"] for e in out] == [KEYPAD, FREQ]


def test_explain_skips_ignored_blind_attributes_and_unknown_models():
    assert _explain({FREQ: "VHF"}, ignore_attrs={FREQ}) == []
    with patch.object(ddb, "_load_all_tables", return_value=(EXPLAIN_ROWS, [], [], [], [])):
        assert ddb.explain_known_attrs("NOPE", {FREQ: "VHF"}, 1267) == []
        assert ddb.explain_known_attrs("", {"a": "b"}, 1267) == []


def test_explain_agrees_with_the_derivation():
    """The replay and the real derivation narrow the same way: one remaining means a base model is derived."""
    with patch.object(ddb, "_load_all_tables", return_value=(EXPLAIN_ROWS, [], [], [], [])):
        assert ddb.derive_base_model_from_known_attrs("APX900", {FREQ: "VHF"}, 1267) == "A"
        assert ddb.derive_base_model_from_known_attrs("APX900", {FREQ: "700-800 MHz"}, 1267) is None
    assert _explain({FREQ: "VHF"})[0]["remaining_after"] == 1
    assert _explain({FREQ: "700-800 MHz"})[0]["remaining_after"] == 4
