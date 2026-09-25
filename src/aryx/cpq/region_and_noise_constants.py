"""Country-to-region mapping and layout/noise variable-name fragment
allowlists, split out of `cpq/engine.py`'s module-level scope (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md -- module-level constant
extraction, done purely to shrink engine.py further). Re-exported from
`aryx.cpq.engine` (see the import there) so every existing `from
aryx.cpq.engine import <name>` caller/test keeps working unchanged.
Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

# Country -> standard sales-region abbreviation. Deliberately covers only
# the unambiguous majority; countries not listed here fall through to the
# normal "ask" behavior rather than guess. Two catalog-observed codes are
# intentionally NOT targeted by this map: "AP" and "EA" overlap with APAC
# for Asian countries with no reliable way to disambiguate from country
# name alone — Asian countries resolve to "APAC" (the more universal code)
# and AP/EA stay reachable only by explicit user answer. This is a business
# judgment call, not a technical limitation; revisit if wrong.
_COUNTRY_TO_REGION: dict[str, str] = {
    # North America
    "united states": "NA", "us": "NA", "usa": "NA", "u.s.": "NA", "u.s.a.": "NA",
    "canada": "NA", "mexico": "NA",
    # Latin America
    "brazil": "LA", "argentina": "LA", "chile": "LA", "colombia": "LA", "peru": "LA",
    "venezuela": "LA", "ecuador": "LA", "uruguay": "LA", "paraguay": "LA", "bolivia": "LA",
    "costa rica": "LA", "panama": "LA", "guatemala": "LA", "honduras": "LA",
    "el salvador": "LA", "nicaragua": "LA", "dominican republic": "LA", "jamaica": "LA",
    # EMEA (Europe + Africa — Middle East kept separate, see below)
    "united kingdom": "EMEA", "uk": "EMEA", "germany": "EMEA", "france": "EMEA",
    "italy": "EMEA", "spain": "EMEA", "netherlands": "EMEA", "belgium": "EMEA",
    "switzerland": "EMEA", "austria": "EMEA", "sweden": "EMEA", "norway": "EMEA",
    "denmark": "EMEA", "finland": "EMEA", "poland": "EMEA", "ireland": "EMEA",
    "portugal": "EMEA", "greece": "EMEA", "czech republic": "EMEA", "romania": "EMEA",
    "south africa": "EMEA", "nigeria": "EMEA", "kenya": "EMEA", "egypt": "EMEA",
    # Middle East
    "saudi arabia": "ME", "united arab emirates": "ME", "uae": "ME", "qatar": "ME",
    "israel": "ME", "kuwait": "ME", "bahrain": "ME", "oman": "ME", "jordan": "ME",
    # Asia Pacific
    "china": "APAC", "japan": "APAC", "india": "APAC", "australia": "APAC",
    "singapore": "APAC", "south korea": "APAC", "korea": "APAC", "indonesia": "APAC",
    "malaysia": "APAC", "thailand": "APAC", "philippines": "APAC", "vietnam": "APAC",
    "new zealand": "APAC", "taiwan": "APAC", "hong kong": "APAC",
}


def region_for_country(raw_country: str, region_map: dict[str, str] | None = None) -> str:
    """`_COUNTRY_TO_REGION`, but resolves an ISO alpha-2/alpha-3 code (e.g.
    "CA", "DE") to its canonical name first, so only "us"/"uk"/"uae" being
    literal keys in the map above no longer means every other country's
    CODE silently fails to resolve a region (CPQ_Hardcode_Audit_dev_oci_
    2026-09-25.md T5). Reuses the 249-country ISO alias system `country/
    country_alias_data.py` already built for country *validation*, rather
    than hand-adding more per-country literals to this map -- the same
    fix shape as that system's own docstring describes for the analogous
    bug it already closed elsewhere.

    Falls back to the original direct-lookup behavior (plain lowercase/
    strip, no alias resolution) when the alias system doesn't recognize
    the input at all -- never worse than the pre-fix behavior, only
    better for the codes/names it can now resolve.

    `region_map` defaults to this module's own `_COUNTRY_TO_REGION` --
    callers that need to keep an existing `patch("...`_COUNTRY_TO_REGION",
    ...)` test point working (e.g. tests patching `aryx.cpq.engine.
    _COUNTRY_TO_REGION`, which this function otherwise wouldn't see) pass
    that same reference through explicitly.
    """
    from aryx.cpq.country.country_helpers import (
        _country_alias_group, _country_canonical_name, _normalize_country_candidate,
    )
    table = region_map if region_map is not None else _COUNTRY_TO_REGION
    normalized = _normalize_country_candidate(raw_country)
    group = _country_alias_group(normalized)
    if group is not None:
        canonical = _country_canonical_name(group).lower()
        region = table.get(canonical, "")
        if region:
            return region
    return table.get(raw_country.strip().lower(), "")


# CPQ layout-noise types — exclude from configuration conversation.
_LAYOUT_TYPE_FRAGMENTS: frozenset[str] = frozenset({
    "layout", "prop", "css", "display_type", "view",
})

# Noise attr variable_name fragments — skip these entirely at load time.
# Catches TestPager, TestPager2, Error, dummy_* etc.
_NOISE_VAR_FRAGMENTS: frozenset[str] = frozenset({
    "test", "pager", "error", "dummy",
})

# Noise item_value / display_name fragments — strip these options at load time.
_NOISE_ITEM_FRAGMENTS: frozenset[str] = frozenset({
    "test", "dummy", "pager",
})
