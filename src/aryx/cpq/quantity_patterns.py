"""Quantity-extraction regex patterns and plausibility bounds, split out
of `cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction beyond
the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re

# Session-level product quantity extraction (docs/CPQ_QUANTITY_SLOTFILLING_
# AND_UI_ISSUES_PLAN_2026_08_11.md) -- a number adjacent to a quantity-
# indicating word or "units"/product-noun phrasing, never a bare number
# anywhere in the message (a model code, a year, a street address digit
# would all be wrongly captured otherwise). Longest/most specific patterns
# first so "50 in qty" doesn't get short-circuited by a looser alternative.
# PR #186 review, critical #1: every pattern's digit group needs a LEFT
# boundary too, not just the trailing `(?!\.\d)` guard -- `\d+` has no
# built-in word-start requirement, so it can start matching mid-identifier.
# Confirmed live: "quote me 5 APX8000 radios" -- the real "5" isn't
# directly followed by "radios" (that "APX8000" is in the way) so it never
# matches, but "8000" lifted straight out of "APX8000" IS directly
# followed by " radios" and matches instead, silently becoming the
# quantity. `(?<![\w.\-])` immediately before the digit group rejects any
# match whose digit run is glued onto a preceding letter/digit/word
# character OR a hyphen (a model code like "APX8000" or "APX-5000", a
# decimal fraction) -- redundant but harmless on patterns that already
# require preceding whitespace via a literal keyword phrase. The hyphen
# exclusion (review follow-up) still allows a genuine negative quantity
# ("quantity is -5") since that "-" is itself preceded by whitespace, not
# by the digit group's own left edge.
# Named separately (not inline in the list literal) so `extract_quantity_
# hint` can identify it by reference and apply the year exclusion against
# the FULL captured digit string -- see the comment where it's used in
# `_QUANTITY_PATTERNS` below.
_MODEL_QUANTITY_PATTERN = re.compile(
    r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:models?)\b"
)

_QUANTITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i:\bqty\s+of\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s+of\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s+(?:is|to|as)\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bqty\s*[:=]?\s*)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # "qty to N" -- live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_
    # EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 6): the "quantity"
    # pattern above already supports "is|to|as", but "qty" (its own
    # common shorthand) only ever supported the bare/colon/equals form,
    # so "update qty to 30" silently matched nothing while "update
    # quantity to 30" worked.
    re.compile(r"(?i:\bqty\s+(?:is|to|as)\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s*[:=]?\s*)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:in\s+qty)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:qty)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:units?)\b"),
    re.compile(r"(?i:\bi\s+want\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bneed\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # "I need pricing for a dozen X" / "...for 12 X" -- live-verified gap,
    # 2026-08-13: the bare "need N" pattern above requires the number
    # RIGHT after "need", so "need pricing for N" (a very common real
    # quoting phrasing) never matched at all, regardless of digit vs
    # word-form. Anchored on the fixed phrase "pricing for" specifically
    # (not a general "for N" pattern) to keep the same narrow-adjacency
    # safety discipline as every other pattern here -- never a bare number
    # anywhere in the message.
    re.compile(r"(?i:\bpricing\s+for\s+(?:an?\s+)?)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # Tolerates up to 3 intervening words between the number and the unit
    # noun ("15 APX NEXT radios") -- live-verified gap, 2026-08-13 (docs/
    # CPQ_QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 5): every
    # pattern here used to require the number strictly ADJACENT to its
    # context word, so a product name sitting between them (the single
    # most common real quoting phrasing) matched nothing at all. Each
    # intervening word must be PURELY alphabetic (no digit anywhere in
    # it) -- a model code glued to digits ("APX8000") must still block
    # the match entirely (PR #186 review, critical #1's existing guard),
    # never be treated as an acceptable "product name" word, and this
    # can never stretch across into an unrelated, separately-stated
    # number later in the same sentence either.
    re.compile(
        r"(?<![\w.\-])(-?\d+)(?!\.\d)\s+(?:[A-Za-z][A-Za-z'-]*\s+){0,3}"
        r"(?i:radios?|devices?|pieces?|pcs)\b"
    ),
    # "model(s)" -- live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_
    # EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 4): "the 2026 model"
    # stated no order quantity at all, but the combined pattern above
    # matched "2026" as if it were one, since a year and a genuine
    # quantity look identical to a bare regex. The year exclusion itself
    # is NOT encoded in this pattern (a fixed-width lookbehind here would
    # only ever inspect the last 4 characters of an arbitrarily long
    # digit run, wrongly rejecting real 5+-digit quantities like 12026 or
    # 32026 whose TRAILING 4 digits happen to look like a year -- PR
    # review finding, 2026-08-13) -- it's applied in `extract_quantity_
    # hint` below, which can check the FULL captured digit string's
    # length before deciding it's a year.
    _MODEL_QUANTITY_PATTERN,
]

# PR #186 review, medium: decimal variants of the same patterns above,
# checked BEFORE the integer patterns run. Without this, a decimal like
# "10.0" gets rejected from matching as "10" by `(?!\.\d)` as intended,
# but the regex engine then backtracks and matches the trailing "0" after
# the decimal point instead of failing outright -- silently turning
# "change quantity to 10.0" into quantity=0. Derived by substituting each
# pattern's own `(-?\d+)(?!\.\d)` integer group for a `(-?\d+\.\d+)`
# decimal group, so the two lists can never drift out of sync with each
# other.
_QUANTITY_DECIMAL_PATTERNS: list[re.Pattern] = [
    re.compile(
        p.pattern.replace(r"(?<![\w.\-])(-?\d+)(?!\.\d)", r"(?<![\w.\-])(-?\d+\.\d+)")
    )
    for p in _QUANTITY_PATTERNS
]

# PR #186 review, critical #2: a thousands-separator comma between two
# digit groups ("1,000") sits at a real word boundary, so an integer
# pattern happily matches just the "1" before it and silently truncates
# the stated quantity -- no rejection, no indication anything was
# mangled. Stripped before any pattern runs, so "1,000" is treated
# exactly like "1000" was always the input. Deliberately narrow (exactly
# 3 digits after the comma, comma glued to digits on both sides) so it
# never touches an ordinary list separator like "5, 1000 items".
_THOUSANDS_SEPARATOR_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")

# A real order is somewhere between "at least one" and "not an absurd
# typo/overflow" -- callers use this to decide whether an extracted number
# is a plausible quantity at all, distinct from "no number found" (None).
# 100,000 units of a single product line is already far beyond any real
# order this catalog has ever seen; treated as a probable typo, not a
# genuine bulk order, same "never silently accept an implausible value"
# discipline the rest of this module already applies elsewhere.
MIN_PRODUCT_QUANTITY = 1
MAX_PRODUCT_QUANTITY = 100_000


def is_valid_product_quantity(value: int) -> bool:
    """True for a real, plausible order quantity -- rejects zero, negative,
    and absurdly large values. Never silently coerces (e.g. clamps a
    negative to 0 or a huge number down to the max) -- callers must reject
    and ask again, not guess what the customer actually meant."""
    return MIN_PRODUCT_QUANTITY <= value <= MAX_PRODUCT_QUANTITY
