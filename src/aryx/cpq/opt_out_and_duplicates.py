"""Optional-attr empty-fill allowlist, catalog-declared opt-out option
detection, and duplicate-display-name resolution, split out of `cpq/
engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md -- module-level constant/helper extraction, done
purely to shrink engine.py further). Re-exported from `aryx.cpq.engine`
(see the import there) so every existing `from aryx.cpq.engine import
<name>` caller/test keeps working unchanged. Logic unchanged from the
original inline definitions.
"""

from __future__ import annotations

import re
from typing import Any

# Multi-select attrs individually confirmed (Attrsequence: 0 Required rows
# across every base model checked, workspace 93) to be genuinely optional
# add-on choices with no active governance forcing a selection --
# "customer wants none of these" is itself a real, valid, low-risk answer
# for these three, unlike blind-picking a real business choice among them.
# Distinct from _sole_opt_out_option (which finds a literal "None"/"not
# needed" MENU ITEM the catalog authored): none of these three carry such
# an option, so that existing mechanism can't resolve them -- this is a
# separate case, "the attr itself can validly stay empty," not "the menu
# declares an opt-out value." Never applied generically: an attr not
# individually verified genuinely optional here still falls through to
# the existing blind-pick-first-option fallback (or asks), same as
# before this addition.
#   - promoApplicationServices_astro ("Promo Application Services"):
#     0/12 Attrsequence rows Required.
#   - additionalApplicationServices_astro ("Additional Application
#     Services"): 0/85 Attrsequence rows Required.
#   - aTAKNonPromoApplicationServices_astro ("ATAK Non-Promo Application
#     Services"): zero Attrsequence rows at all (also hidden by its own
#     rule unless ATAK is explicitly enabled).
_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS: frozenset[str] = frozenset({
    "promoApplicationServices_astro",
    "additionalApplicationServices_astro",
    "aTAKNonPromoApplicationServices_astro",
})

# Catalog-agnostic "this is the opt-out choice" phrasing -- an attr with
# no real fill justification (`_no_real_fill_justification`) still has a
# safe, non-guessed answer available when exactly one of its menu options
# itself says "nothing needed here" (e.g. preSalesEnggAcknowledgement_
# astro's "Add-on sale, new system components or SI services are not
# required"). This is fundamentally different from blind-picking among
# several real business choices (_BLIND_FILL_RISK_ACCEPTED_VNS) -- it's
# recognizing the customer's own catalog already offers a declared
# "skip" answer, the same concept next_question_prompt's own "(Optional
# — say 'skip' or 'none needed')" hint already surfaces conversationally.
# Deliberately requires EXACTLY one match -- 2+ matches means the menu's
# phrasing is ambiguous about which is the real opt-out, and guessing
# between them would be exactly the guess-risk this whole mechanism
# exists to avoid, so it falls through to asking instead.
_OPT_OUT_OPTION_RE = re.compile(
    r"\bnot\s+(?:required|needed|applicable)\b"
    r"|\bnone\s+(?:needed|required)\b"
    r"|\bn/?a\b"
    r"|\bno(?:t)?\s+(?:action|service|item)s?\s+(?:required|needed)\b",
    re.IGNORECASE,
)


def _sole_opt_out_option(valid_opts: list[Any]) -> Any | None:
    matches = [
        o for o in valid_opts
        if _OPT_OUT_OPTION_RE.search(o.display_name or "")
        or _OPT_OUT_OPTION_RE.search(o.item_value or "")
    ]
    return matches[0] if len(matches) == 1 else None


# Some catalog attributes carry two menu options with the IDENTICAL
# display_name but different item_value (a real BigMachines authoring
# duplicate, not an ingestion artifact -- confirmed live in the raw XML
# export for applicationServicesIntroBundle_astro: item_value "5 YEAR"
# (order 5) and "5 YEARS" (order 8) both display as "5 Year"). Before
# this fix, apply_answer's exact-display-name match returned whichever
# duplicate came first in option order, regardless of which one any
# governing rule actually keys off. Live-traced: the hiding rule that
# keeps additionalApplicationServices_astro visible only recognizes the
# literal "5 YEARS" (plural) -- matching the singular "5 YEAR" duplicate
# left the attribute stuck hidden even after the customer answered the
# duration question. Named per-attribute map (not a generic
# first/last-wins heuristic) so only individually verified duplicates
# get resolved; an unlisted attribute's duplicate options still fall
# through to first-match, same as before.
_DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE: dict[str, str] = {
    "applicationServicesIntroBundle_astro": "5 YEARS",
}
