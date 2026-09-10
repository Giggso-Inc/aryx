"""Tests for _rank_value_candidates_by_relevance and its wiring into
build_candidate_bundles — docs/CPQ_VALUE_CANDIDATE_TRUNCATION_PLAN_2026_08_21.md.

Live-reproduced bug: a 328-option real catalog attribute (Product) truncated
_VALUE_CAP=40 candidates in raw storage order, silently excluding a
customer-named, exact-match value sitting at index 323-325 — the gateway
then correctly (from its own truncated view) reported the value "not a
valid option," degrading to a false disambiguation or a discarded-value
re-ask. Fix: exact matches always survive; the rest are ranked by
rarity-weighted word overlap instead of raw storage order.
"""
from __future__ import annotations

from aryx.cpq.intent_gateway.intent_gateway import (
    _VALUE_CAP,
    _rank_value_candidates_by_relevance,
    build_candidate_bundles,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*pairs: tuple[str, str]) -> list[MenuOption]:
    return [
        MenuOption(item_value=iv, display_name=dn, order=i)
        for i, (iv, dn) in enumerate(pairs)
    ]


def _attr(vn: str, label: str, options: list[MenuOption]) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=label,
        required=False, default_value="", options=options,
    )


# ── _rank_value_candidates_by_relevance: pure-function tests ─────────────

def test_exact_match_survives_regardless_of_score():
    options = _menu(
        *[(f"NOISE {i}", f"Noise Option {i}") for i in range(50)],
        ("APX NEXT XE 4G LTE PLUS 5G", "APX NEXT XE (4G LTE+5G)"),
    )
    q_words = {"change", "product", "to", "apx", "next", "xe", "4g", "lte", "5g"}
    ranked = _rank_value_candidates_by_relevance(
        options, q_words, "change the product to apx next xe (4g lte+5g)",
    )
    assert ranked[0].display_name == "APX NEXT XE (4G LTE+5G)"


def test_exact_match_is_case_insensitive():
    options = _menu(("A", "Baseline Release"), ("B", "Other"))
    ranked = _rank_value_candidates_by_relevance(
        options, {"baseline", "release"}, "set software to BASELINE RELEASE",
    )
    assert ranked[0].display_name == "Baseline Release"


def test_exact_match_on_item_value_also_survives():
    options = _menu(("ATT/FIRSTNET", "ATT/FirstNet (provided by Motorola)"), ("B", "Other"))
    q_words = {"set", "carrier", "to", "att", "firstnet"}
    ranked = _rank_value_candidates_by_relevance(
        options, q_words, "set carrier to att/firstnet",
    )
    assert ranked[0].item_value == "ATT/FIRSTNET"


def test_rarity_weighted_ordering_outranks_raw_overlap_count():
    """A rare, distinctive word match should outrank a match on a generic
    word shared by many options — mirrors the exact bug _resolve_target_
    description's own docstring documents for raw overlap-count scoring."""
    options = _menu(
        ("A", "APX NEXT Multi"),
        ("B", "APX NEXT Single"),
        ("C", "APX NEXT Enhanced"),
        ("D", "APX NEXT Basic"),
        ("E", "APX NEXT XE All Band"),  # only one with "xe" and "band"
    )
    q_words = {"switch", "to", "the", "xe", "band", "one"}
    ranked = _rank_value_candidates_by_relevance(
        options, q_words, "switch to the xe band one",
    )
    assert ranked[0].display_name == "APX NEXT XE All Band"


def test_zero_overlap_and_no_exact_match_is_a_stable_noop():
    """Genuinely zero lexical evidence -- correctly NOT this function's job
    to fix (should fall through to a clarifying question upstream, not be
    guessed at here). Confirms no crash and a stable, deterministic order."""
    options = _menu(("A", "Baseline Release"), ("B", "Enhanced Release"))
    ranked = _rank_value_candidates_by_relevance(
        options, {"totally", "unrelated", "words"}, "totally unrelated words",
    )
    assert {o.display_name for o in ranked} == {"Baseline Release", "Enhanced Release"}


def test_survives_truncation_past_value_cap_when_named_verbatim():
    """The exact live-reproduced shape: a large catalog (300+ options) with
    the target value sitting far past _VALUE_CAP in storage order."""
    noise = [(f"NOISE {i}", f"Legacy SKU {i}") for i in range(320)]
    options = _menu(*noise, ("APX NEXT ENHANCED", "APX NEXT Enhanced"),
                     ("APX NEXT XE 4G LTE PLUS 5G", "APX NEXT XE (4G LTE+5G)"))
    assert len(options) > _VALUE_CAP
    q_words = {"change", "the", "product", "to", "apx", "next", "enhanced"}
    ranked = _rank_value_candidates_by_relevance(
        options, q_words, "change the product to apx next enhanced",
    )
    top = ranked[:_VALUE_CAP]
    assert any(o.display_name == "APX NEXT Enhanced" for o in top), (
        "the named value must survive _VALUE_CAP truncation instead of "
        "being lost in raw storage order"
    )


# ── build_candidate_bundles: end-to-end wiring ────────────────────────────

def test_build_candidate_bundles_surfaces_far_index_exact_match():
    """Regression test for the live bug: Product-shaped attr with 328
    options, target value at index 325 (past _VALUE_CAP=40), named
    verbatim in the message — must appear in the bundle sent to the LLM."""
    noise = [(f"LEGACY SKU {i}", f"Legacy SKU {i}") for i in range(325)]
    options = _menu(
        *noise,
        ("APX NEXT ENHANCED", "APX NEXT Enhanced"),
        ("APX NEXT XE 4G LTE PLUS 5G", "APX NEXT XE (4G LTE+5G)"),
        ("APX NEXT ALL BAND", "APX NEXT All Band"),
    )
    assert len(options) == 328
    product_attr = _attr("productSelectionProduct_all", "Product", options)
    session = CpqSession()
    session.filled = {"productSelectionProduct_all": "APX NEXT ENHANCED"}

    bundles = build_candidate_bundles(
        [product_attr], session, "change the product to APX NEXT XE (4G LTE+5G)",
    )
    bundle = next(b for b in bundles if b.attr.variable_name == "productSelectionProduct_all")
    assert len(bundle.values) <= _VALUE_CAP
    assert any(v.display_name == "APX NEXT XE (4G LTE+5G)" for v in bundle.values), (
        "the customer-named, exact-match value must survive truncation into "
        "the actual bundle sent to the LLM, not just the ranking helper"
    )


def test_build_candidate_bundles_unrelated_attr_unaffected():
    """A small-option attribute (never truncated either way) must see no
    behavior change — same values, same count, order is a don't-care."""
    hw_attr = _attr("hWVersion_astro", "Hardware Version", _menu(
        ("H1", "APX NEXT (4G LTE+5G)"), ("H2", "APX NEXT (4G LTE Only)"),
    ))
    session = CpqSession()
    bundles = build_candidate_bundles([hw_attr], session, "change hardware version")
    bundle = bundles[0]
    assert {v.display_name for v in bundle.values} == {
        "APX NEXT (4G LTE+5G)", "APX NEXT (4G LTE Only)",
    }
