"""Spelled-out quantity word parsing ("twenty-five", "half a dozen"),
split out of `cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction
beyond the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re

from aryx.cpq.quantity_patterns import _THOUSANDS_SEPARATOR_RE


# Spelled-out quantities ("I want ten APX Next", "twenty-five units") --
# a customer typing the number as a word is exactly as valid as typing a
# digit, and neither the client's report nor a reasonable customer would
# expect one to work and not the other. Deliberately covers "and" only as
# glue between words already in a real number run ("one hundred and
# fifty"), never as a standalone match -- "one" is a valid START token,
# "and" is not, so ordinary text containing "and" is never mistaken for a
# number.
_ONES_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS_WORDS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE_WORDS = {"hundred": 100, "thousand": 1000, "dozen": 12}
_NUMBER_WORDS = {**_ONES_WORDS, **_TENS_WORDS, **_SCALE_WORDS}
_SIGN_WORDS = {"negative", "minus"}
# Fraction/count modifiers before a scale word ("half a dozen" -> 6, "a
# couple dozen" -> 24) -- live-verified gap, 2026-08-13 (docs/CPQ_
# QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 2): neither
# "half" nor "couple" is a number word, so `_NUMBER_WORD_RUN_RE` used to
# match only the bare scale word ("dozen"), silently dropping the
# modifier and reporting 12 instead of 6/24.
_FRACTION_MODIFIERS = {"half": 0.5}
_COUNT_MODIFIERS = {"couple": 2}
_NUM_WORD_ALT = "|".join(_NUMBER_WORDS)
_MODIFIER_ALT = r"(?:half\s+(?:a\s+)?|(?:a\s+)?couple\s+(?:of\s+)?)"
_NUMBER_WORD_RUN_RE = re.compile(
    rf"\b(?:(?:negative|minus)[\s-]+)?(?:{_MODIFIER_ALT})?(?:{_NUM_WORD_ALT})"
    rf"(?:[\s-]+(?:and[\s-]+)?(?:{_NUM_WORD_ALT}))*\b",
    re.IGNORECASE,
)


def _words_to_number(phrase: str) -> int | None:
    """"twenty-five" -> 25, "one hundred and fifty" -> 150,
    "negative five" -> -5, "half a dozen" -> 6, "a couple dozen" -> 24 --
    None if any token isn't a recognized number word (never guess a
    partial parse). A leading sign word must produce a real negative
    result, never silently drop the sign and return the magnitude as if
    it were positive."""
    tokens = [
        t for t in re.split(r"[\s-]+", phrase.strip().lower())
        if t and t not in ("and", "a", "of")
    ]
    if not tokens:
        return None
    negative = tokens[0] in _SIGN_WORDS
    if negative:
        tokens = tokens[1:]
    if not tokens:
        return None
    multiplier: float = 1
    if tokens[0] in _FRACTION_MODIFIERS:
        multiplier = _FRACTION_MODIFIERS[tokens[0]]
        tokens = tokens[1:]
    elif tokens[0] in _COUNT_MODIFIERS:
        multiplier = _COUNT_MODIFIERS[tokens[0]]
        tokens = tokens[1:]
    if not tokens:
        return None
    total = 0
    current = 0
    for tok in tokens:
        if tok in _NUMBER_WORDS:
            val = _NUMBER_WORDS[tok]
            # Identity check (which WORD it is), never a value check --
            # "twelve" (a _ONES_WORDS entry worth 12) must never be
            # mistaken for the scale word "dozen" just because they share
            # the same numeric value (docs/CPQ_QUANTITY_EXTRACTION_
            # DEFECTS_PLAN_2026_08_13.md cluster 1: "one hundred and
            # twelve" was silently becoming 1200, treating "twelve" as a
            # second multiplier applied on top of "hundred").
            if tok in _SCALE_WORDS:
                current = (current or 1) * val
                if val >= 1000:
                    total += current
                    current = 0
            else:
                current += val
        else:
            return None  # unrecognized token -- abort, never guess
    result = (total + current) * multiplier
    if isinstance(result, float):
        if not result.is_integer():
            return None  # a fractional quantity is never a valid whole count
        result = int(result)
    return -result if negative else result


def _substitute_number_words(text: str) -> str:
    """Replaces every recognizable number-word run with its digit form so
    the existing digit-anchored _QUANTITY_PATTERNS can match it unchanged
    -- e.g. "I want ten APX Next" -> "I want 10 APX Next". A run whose
    words don't form a valid number (shouldn't happen given the regex only
    matches known number words, but kept as a safety net) is left as-is."""
    def _replace(m: re.Match) -> str:
        value = _words_to_number(m.group(0))
        return str(value) if value is not None else m.group(0)
    return _NUMBER_WORD_RUN_RE.sub(_replace, text)


# A sign WORD directly before a DIGIT ("minus 5", "negative 12") --
# live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_EXTRACTION_DEFECTS_
# PLAN_2026_08_13.md cluster 3): `_SIGN_WORDS` is only ever consulted
# inside `_words_to_number`, which only runs on a matched number-WORD
# run -- a bare digit after a sign word never reaches it at all, so
# "minus 5 units" silently became +5 (the digit-only pattern `(-?\d+)`
# only recognizes a literal "-" character glued to the digit, never the
# word "minus" with a space before the digit). Normalized to the
# literal sign form ("minus 5" -> "-5") before either the decimal or
# integer patterns run, so both paths see it identically.
_SIGN_WORD_DIGIT_RE = re.compile(r"(?i:\b(?:negative|minus)\b)[\s-]+(?=\d)")


def _normalize_quantity_text(text: str) -> str:
    """Shared preprocessing for both the decimal check and the integer
    patterns -- quote-stripping and thousands-separator removal must
    happen identically for both, or a comma/quote could dodge one path
    and not the other."""
    text = re.sub(
        r"[\"'‘’“”]([A-Za-z0-9-]+)[\"'‘’“”]",
        r"\1", text,
    )
    text = _SIGN_WORD_DIGIT_RE.sub("-", text)
    return _THOUSANDS_SEPARATOR_RE.sub("", text)
