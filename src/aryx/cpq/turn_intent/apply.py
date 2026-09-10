"""``apply_answer`` -- resolve a user's free-text/menu-option answer for a
single-select attribute (Phase 4 step 2 extraction from ``cpq/engine.py``,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless -- needs no
engine-instance callback.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import (
    _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE,
    _option_matches_with_unit_normalization,
    _presentable,
    _valid,
)
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.apply_country_alias import country_alias_fallback


def apply_answer(
    attr: ConfigAttr,
    user_answer: str,
    constrained_item_values: list[str] | None = None,
) -> tuple[str, str] | None:
    """Match the user's natural-language answer to a valid option.

    constrained_item_values — when active constraint rules apply (same
    set passed to `next_question_prompt`), only these item_values may
    match — an answer for an option outside the currently-allowed set
    is rejected rather than silently accepted (Phase I).

    Returns (item_value, display_name) or None if no match found.
    """
    ua = user_answer.strip().lower()
    # docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_PLAN_2026_08_
    # 21.md -- live-confirmed: "2Yrs" (no space, abbreviated unit) fails
    # every tier below against a real "2 Year" option, since "2yrs"
    # tokenizes as one alphanumeric run sharing zero words with "2"+
    # "year". Narrow, scoped normalization -- only a digit directly
    # followed by "yr"/"yrs" -- not a general NLP rewrite; deliberately
    # excludes a bare "y" abbreviation (too collision-prone against
    # real catalog codes like a "Y"/"N" yes/no option).
    ua = re.sub(r"(\d+)\s*yrs?\b", r"\1 year", ua)
    allowed = set(constrained_item_values) if constrained_item_values is not None else None
    options = (
        [o for o in attr.options if o.item_value in allowed]
        if allowed is not None else attr.options
    )

    # Numeric selection: user typed "1", "2", etc. → pick by position in the
    # presented option list (only _presentable options, matching next_question_prompt).
    if ua.isdigit():
        presentable = [o for o in options if _presentable(o.item_value)]
        idx = int(ua) - 1
        if 0 <= idx < len(presentable) and _valid(presentable[idx].item_value):
            return presentable[idx].item_value, presentable[idx].display_name

    # Known catalog duplicates -- two menu options share the same
    # display_name (a real BigMachines authoring duplicate, see
    # _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE) so a plain-text
    # reply like "5 year" can coincidentally exact-match one
    # duplicate's item_value ("5 YEAR") while the OTHER duplicate is
    # the one governing rules actually key off ("5 YEARS"). Checked
    # ahead of both the item_value and display-name exact-match
    # tiers below so the coincidental item_value hit can't win first.
    canonical_value = _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE.get(
        attr.variable_name)
    if canonical_value is not None:
        for opt in options:
            if opt.item_value == canonical_value and (
                opt.item_value.lower() == ua or opt.display_name.lower() == ua
            ):
                return opt.item_value, opt.display_name

    # Exact item_value match
    for opt in options:
        if opt.item_value.lower() == ua:
            return opt.item_value, opt.display_name

    # Exact display-name match
    for opt in options:
        if opt.display_name.lower() == ua:
            if _valid(opt.item_value):
                return opt.item_value, opt.display_name

    # User answer contained in option's display name (user typed a prefix)
    for opt in options:
        if ua in opt.display_name.lower():
            if _valid(opt.item_value):
                return opt.item_value, opt.display_name

    # Option display name found in user answer with word boundaries on both sides.
    # Uses (?<!\w)…(?!\w) rather than \b because standard \b fails at the end
    # of names like "APX NEXT (4G LTE Only)" where the trailing ")" is a
    # non-word char with no \b transition. Sorted longest-first so
    # "APX NEXT (4G LTE Only)" wins over "APX NEXT" when both could match.
    # The right-side (?!\w) also blocks short codes like "AP" from matching
    # inside "APX" — "ap" followed by "x" fails (?!\w).
    for opt in sorted(options, key=lambda o: len(o.display_name), reverse=True):
        dn = opt.display_name.lower()
        if re.search(r"(?<!\w)" + re.escape(dn) + r"(?!\w)", ua):
            if _valid(opt.item_value):
                return opt.item_value, opt.display_name

    # Option display name found as a whole WORD in user answer — word-boundary
    # prevents "me" (Middle East code) from matching in "north a*me*rica".
    for opt in options:
        dn_lower = opt.display_name.lower()
        if re.search(r"\b" + re.escape(dn_lower) + r"\b", ua):
            if _valid(opt.item_value):
                return opt.item_value, opt.display_name

    # Unit/pluralization-tolerant match — "2 Yrs" or "2 Years" against
    # a catalog option displayed as "2 Year" (confirmed live: neither
    # form ever matched, so the value was silently dropped and the
    # session kept reporting the old one as still current). See
    # _option_matches_with_unit_normalization for the generic
    # token-comparison this relies on — no per-unit synonym table.
    for opt in sorted(options, key=lambda o: len(o.display_name), reverse=True):
        if _option_matches_with_unit_normalization(opt.display_name, ua):
            if _valid(opt.item_value):
                return opt.item_value, opt.display_name

    # See apply_country_alias.py — split out purely to keep this file
    # under the file-size cap.
    alias_match = country_alias_fallback(attr, user_answer, ua, options)
    if alias_match:
        return alias_match

    # Free-text field
    if not attr.options and allowed is None and _valid(user_answer):
        return user_answer.strip(), user_answer.strip()

    return None
