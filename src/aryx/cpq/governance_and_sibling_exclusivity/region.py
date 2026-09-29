"""``derive_region`` -- country-to-region resolution against a Region
attr's real menu options (Phase 4 step 7 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``_COUNTRY_TO_REGION`` and the alias helpers are reached through the
engine MODULE object rather than imported by name -- ``_COUNTRY_TO_
REGION`` is defined well below this package's import point in
``engine.py``, and module-object access defers the lookup to call time.
"""

from __future__ import annotations

import re

from aryx.cpq import engine as _engine_module
from aryx.cpq.state import ConfigAttr


def derive_region(country: str, attr: ConfigAttr) -> tuple[str, str] | None:
    """Resolve a region attr's value from a known country, without
    inventing a code the catalog doesn't actually offer.

    Looks up `country` in `_COUNTRY_TO_REGION` for a standard region
    abbreviation, then matches that abbreviation against `attr`'s real
    menu options (exact item_value first, then display_name) -- a
    country with no mapping, or a catalog whose Region attr doesn't
    offer the derived code, returns None so the caller falls back to
    asking rather than guessing.

    ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_
    17.md): `country` may legitimately arrive as any real alias of a
    country (official name, alpha-2/alpha-3 code, a punctuation
    variant like "us.a" normalized upstream to "United States", ...)
    rather than one of the handful of literal strings
    `_COUNTRY_TO_REGION` happens to spell out as keys. The direct
    lookup below is tried first (fast path, unchanged behavior for
    the exact forms that already worked); only when that misses does
    this resolve `country` to its full alias group and retry the
    lookup against every member of that group -- generic for all 249
    real countries, never a per-country special case -- since
    `_COUNTRY_TO_REGION`'s own keys are already just a few of a
    country's many real aliases (e.g. "us"/"usa"/"united states" are
    all present for the US entry today).
    """
    if not country:
        return None
    region_code = _engine_module._COUNTRY_TO_REGION.get(country.strip().lower())
    if not region_code:
        group = _engine_module._country_alias_group(
            _engine_module._normalize_country_candidate(country)
        )
        if group:
            for alias in group:
                region_code = _engine_module._COUNTRY_TO_REGION.get(alias)
                if region_code:
                    break
    if not region_code:
        return None
    for opt in attr.options:
        if opt.item_value.upper() == region_code:
            return opt.item_value, opt.display_name
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T5: word-boundary match, not
    # bare substring -- "ME" (Middle East) previously matched inside
    # "NORTH AMERICA" (`a-ME-rica`), silently resolving a US/Canada
    # session to the wrong region option. Same fix shape already applied
    # at turn_intent/apply.py's own "me"-in-"america" call site.
    region_word_re = re.compile(r"\b" + re.escape(region_code) + r"\b")
    for opt in attr.options:
        if region_word_re.search(opt.display_name.upper()):
            return opt.item_value, opt.display_name
    return None
