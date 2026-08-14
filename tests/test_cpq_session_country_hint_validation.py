"""Live bug, found during the CPQ layout-visibility-order live verification
(not related to that plan): `extract_hints`' generic preposition-based
country extractor's 2-letter-code alternative has no trailing word-boundary
check, so "for APX Next" matched "for " + "AP" (the first two letters of
"APX") and produced `hints["country"] = "Ap"`.

`session.country` is a "first hint wins, never re-derived" field
(ask_api.py) — once set on turn 1, it's reused verbatim on every later
turn regardless of whether a real answer later fills the actual country
attribute, so this single bad match permanently blocked `derive_region`
for the rest of the session with no way to self-correct.

Fix: `CpqEngine.is_recognized_country` (engine.py) validates a hint
against `_COUNTRY_TO_REGION` before it's allowed into `session.country` at
either of its two hint-derived assignment sites in ask_api.py.
`extract_hints` itself is deliberately left unchanged — the real country
ATTRIBUTE still resolves correctly via direct menu-option matching
regardless of this bug, since that path never went through
`session.country` at all.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


def test_apx_next_no_longer_extracted_as_a_country_hint():
    """The exact real sentence that produced the bug live.

    docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md review finding hardened
    `_COUNTRY_PREP`'s ALLCAPS branch to consume the FULL uppercase run
    (word-bounded) instead of truncating to its first 2 letters -- "APX
    Next" is now captured whole ("Apx Next") rather than mangled into
    "Ap". Still just as unrecognized as a country either way; this test
    now locks in the fuller, still-safe capture instead of the old
    truncated one."""
    eng = CpqEngine()
    hints = eng.extract_hints("I need a quote for APX Next")
    # extract_hints itself still produces only a raw, unvalidated
    # candidate -- the actual protection is is_recognized_country at the
    # session.country assignment sites (ask_api.py), not here.
    assert hints.get("country") == "Apx Next"
    assert not eng.is_recognized_country(hints["country"])


def test_real_country_names_and_codes_still_recognized():
    eng = CpqEngine()
    for value in ("United States", "us", "USA", "Canada", "united kingdom", "UK"):
        assert eng.is_recognized_country(value), f"{value!r} should be recognized"


def test_garbage_and_product_fragments_not_recognized():
    eng = CpqEngine()
    for value in ("Ap", "Apx", "XE", "NA", "APAC"):
        # NA/APAC are real REGION codes, not countries -- must not be
        # accepted into session.country either (derive_region expects a
        # country name/code, not a region code, as its own input).
        assert not eng.is_recognized_country(value), f"{value!r} should NOT be recognized"


def test_full_real_sentence_still_extracts_the_real_country():
    """Regression: the fix must not break genuine country extraction from
    a real, full sentence containing an explicit destination-country
    phrase alongside the "for APX Next" fragment that caused the bug."""
    eng = CpqEngine()
    sentence = (
        "I want to order APX Next radios 50 in qty for customer who is "
        "Houston City of with destination country as United States"
    )
    hints = eng.extract_hints(sentence)
    assert hints.get("country") == "United States"
    assert eng.is_recognized_country(hints["country"])
