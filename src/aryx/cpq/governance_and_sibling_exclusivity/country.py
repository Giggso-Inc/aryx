"""``is_recognized_country`` -- the single shared country-validation gate
(Phase 4 step 7 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The alias-table helpers are reached through the engine MODULE object
rather than imported by name so the extraction can sit anywhere in
``engine.py``'s import order and so a patched helper is still honored.
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module


def is_recognized_country(value: str) -> str | None:
    """The canonical common name (e.g. "United States") when `value`
    is a real, recognized country -- by common name, official name,
    ISO alpha-2/alpha-3 code, or a punctuation/abbreviation variant
    of any of those ("US.A", "U.K", "U.A.E") -- else None.

    ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_
    17.md): previously checked membership in `_COUNTRY_TO_REGION` --
    a small, hand-typed dict of exact strings covering a narrow
    subset of countries, with none of their punctuation/abbreviation
    variants ("us.a" was never a key). Now normalizes the candidate
    (`_normalize_country_candidate`) and checks it against
    `_country_alias_group` -- the comprehensive, symmetric, 249-real-
    country alias table already built for exactly this purpose
    (`engine.py:404+`) -- so any real alias/punctuation/abbreviation
    form of any of the 249 countries resolves here, not just the
    handful the old dict happened to spell out.

    Returns `str | None` rather than the old bare `bool` because this
    is the single shared validation gate for THREE call sites (Path
    B's bare-anchor-reply hint validation, Path C's change-command
    gate, and Path C's downstream LLM-result validation) that all
    need the RESOLVED canonical value, not just a yes/no -- a caller
    that only ever needed the boolean keeps working unmodified, since
    a non-empty string is truthy and `None` is falsy, identical to
    the old bool contract.

    Guards `session.country`'s own assignment (ask_api.py) against a
    real, confirmed live bug: `extract_hints`' generic
    preposition-based country extractor's 2-letter-code alternative
    has no trailing word-boundary check, so "for APX Next" matched
    "for " + "AP" (the first two letters of "APX") and produced
    `hints["country"] = "Ap"`. session.country is a "first hint wins,
    never re-derived" field (ask_api.py) -- once set, it's reused
    verbatim on every later turn regardless of whether a real answer
    ever fills the actual country attribute, so a single bad match
    this early permanently blocks `derive_region` for the rest of the
    session with no way to self-correct. Since `session.country`'s
    only consumer is `derive_region`, and `derive_region` itself
    already returns None for anything it can't resolve a region for,
    rejecting an unrecognized candidate BEFORE it's stored costs
    nothing today and stops it from calcifying into a wrong value
    that can never be replaced by a later, correct hint.

    PR #205 review fix: an earlier version of this exclusion rejected
    ANY candidate matching one of this system's own region codes
    ("NA"/"EMEA"/"ME"/"APAC"/"LA") -- but "ME" is genuinely Montenegro's
    real ISO alpha-2 code and "LA" is genuinely Laos's, so that blanket
    rule silently reintroduced the exact same collision bug for two
    more real countries. The blanket exclusion was never actually
    needed for "EMEA"/"ME"/"APAC"/"LA" in the first place: none of
    those four strings appear in any real country's alias group
    (`_COUNTRY_ALIAS_GROUPS`) as anything OTHER than Montenegro's/
    Laos's own codes, so the alias-group lookup below already returns
    None for "EMEA"/"APAC" on its own -- only "NA" is a genuine,
    confirmed double meaning (this system's own "North America" token
    AND Namibia's real alpha-2 code, confirmed live and locked in by
    test_garbage_and_product_fragments_not_recognized, which predates
    this fix and only exercises "NA"/"APAC", never "ME"/"LA"). Scoped
    to the literal, documented single collision instead of a blanket
    rule across this system's whole region-code namespace.
    """
    _normalized = _engine_module._normalize_country_candidate(value)
    if _normalized.upper() == "NA":
        return None
    group = _engine_module._country_alias_group(_normalized)
    if group is None:
        return None
    return _engine_module._country_canonical_name(group)
