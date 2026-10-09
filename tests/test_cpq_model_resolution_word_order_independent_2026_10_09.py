"""Regression test for the live stale-resolution bug found on ws 1267,
2026-10-09: `model_resolution._match_kind` matched a candidate's display
name by concatenating it into one string (spaces/punctuation stripped) and
checking literal substring containment in the similarly concatenated hint --
so the match only succeeded when the hint said the words in the catalog's
own exact order.

Live: Basemodeltoconfig's displayModel for the Enhanced APX 6500 variant is
"Enhanced APX6500/LI" (adjective-first). A customer asking for "APX 6500
Enhanced" (adjective-last, an equally natural phrasing) normalizes to
"...apx6500enhanced...", which "enhancedapx6500li" is never a substring of --
`ENHANCEDAPX6500/LI` was silently excluded from the candidate pool before
`rank_candidates` ever ran, and the plain (non-Enhanced, data-gap-ridden)
`APX6500/LI` resolved instead.

Fix: `cpq_model_resolution_word_order_independent_enabled` tokenizes both the
candidate's display name and the hint into words. The name's own digit code
(e.g. "apx6500"), or the whole name when it has no digits, must still read
contiguously, in order, in the hint -- this is what stops an unrelated
number elsewhere in an ordinary quote request (a quantity, a battery size,
another model) from matching. A word in front of the code ("Enhanced") must
also be present -- it is what makes the name more specific, so it is not
optional -- while a trailing suffix ("LI") stays optional, same as the
original substring check's own `_CORE_RE` fallback already treats it.
`rank_candidates`'s own `longest_name_match` step (untouched) still prefers
the more specific (more-worded) name once both candidates can match.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc


def _cfg(enabled: bool):
    m = MagicMock()
    m.return_value.cpq_model_resolution_word_order_independent_enabled = enabled
    return m


class FakeRdb:
    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self.rows.get(ontology_type, []))]


def _rdb() -> FakeRdb:
    return FakeRdb({
        "XBmCatalog": [
            {"id": "1", "name": "astro", "parent_id": "-1"},
            {"id": "2", "name": "aPX65005500Series", "parent_id": "1"},
        ],
        "Basemodeltoconfig": [
            {"cpqModel": "APX6500/LI", "displayModel": "APX6500", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T1"},
            {"cpqModel": "APX6500/LI", "displayModel": "APX6500", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T2"},
            {"cpqModel": "ENHANCEDAPX6500/LI", "displayModel": "Enhanced APX6500/LI", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T3"},
            {"cpqModel": "ENHANCEDAPX6500/LI", "displayModel": "Enhanced APX6500/LI", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T4"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })


@pytest.fixture(autouse=True)
def _clean():
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)
    yield
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)


def _resolve(text: str) -> mr.ModelResolution:
    return mr.resolve_model(text, 1, "X", _rdb())


def test_flag_off_keeps_word_order_sensitive_match():
    with patch("aryx.config.get_settings", _cfg(False)):
        res = _resolve("Quote for APX 6500 Enhanced in US")
    assert res.resolved and res.chosen.cpq_model == "APX6500/LI", (
        "flag off: byte-identical to the original word-order-sensitive behavior -- "
        "'Enhanced' trailing the model number still fails to match 'Enhanced APX6500/LI'"
    )


def test_flag_on_resolves_enhanced_variant_regardless_of_word_order():
    with patch("aryx.config.get_settings", _cfg(True)):
        res = _resolve("Quote for APX 6500 Enhanced in US")
    assert res.resolved and res.chosen.cpq_model == "ENHANCEDAPX6500/LI", (
        "flag on: every word of 'Enhanced APX6500/LI' ('enhanced', 'apx6500', 'li') "
        "appears in the hint's tokens regardless of order, and longest_name_match "
        "then prefers it over the shorter plain APX6500/LI"
    )


def test_flag_on_still_matches_the_catalogs_own_word_order():
    """Control: the fix is a strict superset -- a hint that already matches in the
    catalog's own word order must keep matching exactly as before."""
    with patch("aryx.config.get_settings", _cfg(True)):
        res = _resolve("I'd like an Enhanced APX6500/LI please")
    assert res.resolved and res.chosen.cpq_model == "ENHANCEDAPX6500/LI"


def test_flag_on_does_not_add_the_enhanced_variant_to_a_plain_request():
    """Review of this fix (2026-10-09): a prior version let a name's digit code
    match on its own, with the words in front of it ("Enhanced") treated as
    optional -- so a plain "APX 6500" request, which never says "Enhanced" at
    all, would still add ENHANCEDAPX6500/LI to the candidate pool (tied with
    the plain model on match length, then resolved by most_base_models/
    alphabetical -- a model the customer never asked for, picked by accident
    of catalog data rather than by anything they said). Words in front of a
    name's code must now all be present in the hint for that name to match at
    all -- only a trailing suffix ("LI", "XE") stays optional."""
    with patch("aryx.config.get_settings", _cfg(True)):
        res = _resolve("Quote for APX 6500 in US")
    assert res.resolved and res.chosen.cpq_model == "APX6500/LI"
    assert [a.cpq_model for a in res.alternatives] == [], (
        "ENHANCEDAPX6500/LI must not even enter the candidate pool when the "
        "hint never says 'Enhanced'"
    )


def test_flag_on_digit_bleed_guard_preserved_by_whole_word_tokens():
    """Control: tokenizing into whole words naturally preserves the intent of the
    old `_occurs` digit-boundary guard -- "apx6500" as its own token in the hint
    must not accidentally satisfy a candidate word of "apx65005" or similar,
    since tokens are compared for exact equality, not substring containment."""
    rdb = FakeRdb({
        "XBmCatalog": [{"id": "1", "name": "astro", "parent_id": "-1"}],
        "Basemodeltoconfig": [
            {"cpqModel": "APX65005", "displayModel": "APX65005", "baseModel": "T1"},
            {"cpqModel": "APX65005", "displayModel": "APX65005", "baseModel": "T2"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })
    with patch("aryx.config.get_settings", _cfg(True)):
        res = mr.resolve_model("quote an APX6500 please", 1, "X", rdb)
    assert not res.resolved


def _two_model_rdb(cpq_a: str, cpq_b: str) -> FakeRdb:
    return FakeRdb({
        "XBmCatalog": [{"id": "1", "name": "astro", "parent_id": "-1"}],
        "Basemodeltoconfig": [
            {"cpqModel": cpq_a, "displayModel": cpq_a, "baseModel": "T1"},
            {"cpqModel": cpq_a, "displayModel": cpq_a, "baseModel": "T2"},
            {"cpqModel": cpq_b, "displayModel": cpq_b, "baseModel": "T3"},
            {"cpqModel": cpq_b, "displayModel": cpq_b, "baseModel": "T4"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })


@pytest.mark.parametrize(
    "hint,mentioned,unrelated",
    [
        ("Quote for APX 8000 radios, 3000 units", "APX8000", "APX3000"),
        ("I need an APX 6000 with a 3000 mAh battery", "APX6000", "APX3000"),
        ("quote 1000 APX 4500 radios", "APX4500", "APX1000"),
    ],
)
def test_flag_on_does_not_match_an_unrelated_number_elsewhere_in_the_hint(hint, mentioned, unrelated):
    """Review of this fix (2026-10-09): a plain "every word present somewhere"
    check let a quantity, battery size, or any other stray number in an
    ordinary quote request satisfy an unrelated model's digit code, making
    two unconnected models tie for the match. The model's own code (letters
    immediately followed by its number) must read contiguously in the hint,
    not just have its pieces scattered anywhere in it."""
    rdb = _two_model_rdb(mentioned, unrelated)
    with patch("aryx.config.get_settings", _cfg(True)):
        res = mr.resolve_model(hint, 1, "X", rdb)
    assert res.resolved and res.chosen.cpq_model == mentioned, (
        f"expected only {mentioned} (named contiguously) to match, not {unrelated} "
        f"(whose digits merely appear elsewhere in the same sentence)"
    )


def test_flag_on_is_a_strict_superset_of_the_substring_check_by_construction():
    """The word-order-independent path only ever runs as a fallback once
    `_match_kind`'s original substring check has already come up with
    nothing *for that candidate* -- it never overrides or skips a match the
    substring check already found. For wordings the substring check already
    resolves unambiguously (both candidates' names already read in their own
    order), flag on/off must resolve to the exact same model.

    This is distinct from the main "APX 6500 Enhanced" scenario: there, the
    substring check still finds *a* match (the unrelated, wrong plain
    APX6500/LI), so flag-off is resolved too, just resolved wrong -- the fix
    is about which candidate wins the pool, covered by
    `test_flag_on_resolves_enhanced_variant_regardless_of_word_order`, not
    about resolved-vs-unresolved."""
    for hint in ("I'd like an Enhanced APX6500/LI please", "Quote for plain APX6500 please"):
        with patch("aryx.config.get_settings", _cfg(True)):
            on_res = _resolve(hint)
        with patch("aryx.config.get_settings", _cfg(False)):
            off_res = _resolve(hint)
        assert on_res.resolved == off_res.resolved
        if off_res.resolved:
            assert on_res.chosen.cpq_model == off_res.chosen.cpq_model


def test_flag_on_requires_contiguity_for_names_with_no_digit_code():
    """Review of this fix (2026-10-09): a name with no digits at all (roughly
    a third of this catalog's real names -- e.g. "Mobile Radio Kit") has no
    code to anchor on, so without a contiguity requirement its words would
    match as a plain bag of words anywhere in the hint. "kit for mobile
    radio use" must NOT match "Mobile Radio Kit" -- the words are present,
    but not in any contiguous, in-order run, so this is an unrelated
    sentence, not the same product named differently."""
    rdb = FakeRdb({
        "XBmCatalog": [{"id": "1", "name": "astro", "parent_id": "-1"}],
        "Basemodeltoconfig": [
            {"cpqModel": "MOBILERADIOKIT", "displayModel": "Mobile Radio Kit", "baseModel": "T1"},
            {"cpqModel": "MOBILERADIOKIT", "displayModel": "Mobile Radio Kit", "baseModel": "T2"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })
    with patch("aryx.config.get_settings", _cfg(True)):
        bag_of_words = mr.resolve_model("kit for mobile radio use", 1, "X", rdb)
        contiguous = mr.resolve_model("I need a Mobile Radio Kit please", 1, "X", rdb)
    assert not bag_of_words.resolved, "the words are scattered, not a contiguous run -- must not match"
    assert contiguous.resolved and contiguous.chosen.cpq_model == "MOBILERADIOKIT"


def test_tokenize_does_not_cache_hint_text():
    """Review of this fix (2026-10-09): `_tokenize` must stay uncached --
    it runs once per customer message, so caching it would grow a
    process-lifetime dict by one entry per distinct message ever seen in a
    long-running server. Only `_tokenize_name` (catalog names, a small,
    repeating set) should be memoized."""
    assert not hasattr(mr._tokenize, "cache_info"), "_tokenize must not be an lru_cache-wrapped function"
    info_before = mr._tokenize_name.cache_info()
    for i in range(50):
        mr._tokenize(f"a distinct customer message number {i}")
    # _tokenize itself has no cache at all; confirm _tokenize_name's cache --
    # the one memoized function here -- didn't grow just from tokenizing hint
    # text, since hint text never goes through it.
    assert mr._tokenize_name.cache_info().currsize == info_before.currsize
