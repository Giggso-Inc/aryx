"""_OPT_OUT_OPTION_RE -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T7.

n/?a made the slash in "n/a" optional, so a real menu option literally
named "NA" (the North America region/country code) matched the opt-out
detector meant for "N/A" ("not applicable"). "N/A" with its delimiter is
still unambiguous and must still match; only the bare-code collision is
removed.
"""
from __future__ import annotations

from types import SimpleNamespace

from aryx.cpq.opt_out_and_duplicates import _OPT_OUT_OPTION_RE, _sole_opt_out_option


def test_na_region_code_no_longer_matches_the_opt_out_pattern():
    assert _OPT_OUT_OPTION_RE.search("NA") is None
    assert _OPT_OUT_OPTION_RE.search("na") is None


def test_n_slash_a_still_matches_as_a_real_opt_out_phrasing():
    assert _OPT_OUT_OPTION_RE.search("N/A") is not None
    assert _OPT_OUT_OPTION_RE.search("n/a") is not None


def test_sole_opt_out_option_does_not_pick_a_real_na_region_option():
    opts = [
        SimpleNamespace(display_name="NA", item_value="NA"),
        SimpleNamespace(display_name="EMEA", item_value="EMEA"),
        SimpleNamespace(display_name="APAC", item_value="APAC"),
    ]
    assert _sole_opt_out_option(opts) is None, (
        "a real 'NA' region option must never be picked as an opt-out choice"
    )


def test_sole_opt_out_option_still_finds_a_real_n_slash_a_option():
    opts = [
        SimpleNamespace(display_name="N/A", item_value="NA_VALUE"),
        SimpleNamespace(display_name="Standard", item_value="STD"),
    ]
    match = _sole_opt_out_option(opts)
    assert match is not None
    assert match.item_value == "NA_VALUE"
