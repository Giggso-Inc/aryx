"""Overall product-quantity extraction from free text, split out of
`cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction beyond
the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

from aryx.cpq.quantity_patterns import (
    _MODEL_QUANTITY_PATTERN, _QUANTITY_DECIMAL_PATTERNS, _QUANTITY_PATTERNS,
)
from aryx.cpq.quantity_word_numbers import _normalize_quantity_text, _substitute_number_words

def extract_quantity_decimal_hint(text: str) -> str | None:
    """The exact decimal substring (e.g. "10.0", "-3.5") when a decimal
    number sits in one of the same quantity-context positions
    `_QUANTITY_PATTERNS` matches integers in -- None otherwise.

    PR #186 review, medium: exists so a caller building a customer-facing
    rejection message can quote what the customer actually typed ("10.0")
    instead of the wrong, confusing digit `extract_quantity_hint`'s own
    regex backtracking used to produce ("0", the fractional remainder).
    Checked BEFORE `extract_quantity_hint` runs its integer patterns at
    all -- this is a short-circuit, not just an alternate lookup.
    """
    normalized = _normalize_quantity_text(text)
    for pattern in _QUANTITY_DECIMAL_PATTERNS:
        m = pattern.search(normalized)
        if m:
            return m.group(1)
    return None


def _is_year_shaped_model_quantity(digits: str) -> bool:
    """True only when `digits` (the exact captured string, sign included)
    is EXACTLY a 4-digit 19xx/20xx run -- never for a longer number whose
    trailing 4 digits merely happen to look like a year. PR review
    finding, 2026-08-13: a fixed-width regex lookbehind can only ever see
    the last 4 characters before the match position, so it can't tell
    "2026" (a real year, no quantity stated) apart from "...2026" at the
    tail of a longer real quantity like "12026" or "32026" -- both would
    wrongly be rejected if the exclusion were encoded purely as a
    lookbehind inside the pattern itself. Checking the FULL captured
    group's length here, in Python, after the match, gets this right."""
    unsigned = digits[1:] if digits.startswith("-") else digits
    return len(unsigned) == 4 and unsigned[:2] in ("19", "20")


def extract_quantity_hint(text: str) -> int | None:
    """The overall product quantity stated in free text, e.g. "50 in qty",
    "qty of 50", "i want 50", "50 radios" -- None when no supported phrasing
    matches. Deliberately narrow (a number must be adjacent to a quantity-
    indicating word) rather than "the first number found anywhere" -- a raw
    number scan would misread a model code, a year, or an unrelated count
    (like a street address) as the quantity.

    Also recognizes the number spelled out as words ("I want ten APX
    Next", "twenty-five units") -- exactly as valid as a digit from a
    customer's point of view, so it must work exactly the same way. Tried
    only as a fallback (digit forms first): the number-word text is
    substituted with its digit equivalent and re-run through the same
    digit-anchored patterns above, so both forms share one set of
    quantity-context rules rather than duplicating each pattern twice.

    Returns the raw parsed integer, including zero/negative when the text
    actually says so ("change quantity to -5") -- callers must validate
    with `is_valid_product_quantity` before accepting, never assume a
    return value here is automatically a sane quantity. A decimal like
    "1.5"/"10.0" is deliberately never matched at all -- checked via
    `extract_quantity_decimal_hint` FIRST and short-circuited to None
    here, rather than relying solely on each integer pattern's own
    `(?!\\.\\d)` guard, which blocks the direct "10" match but does not
    stop the regex engine from backtracking into the fractional
    remainder instead (PR #186 review, medium: "10.0" was silently
    becoming quantity 0 without this).
    """
    text = _normalize_quantity_text(text)
    if extract_quantity_decimal_hint(text) is not None:
        return None
    for pattern in _QUANTITY_PATTERNS:
        m = pattern.search(text)
        if m:
            if pattern is _MODEL_QUANTITY_PATTERN and _is_year_shaped_model_quantity(m.group(1)):
                continue
            try:
                return int(m.group(1))
            except ValueError:
                continue
    substituted = _substitute_number_words(text)
    if substituted == text:
        return None
    for pattern in _QUANTITY_PATTERNS:
        m = pattern.search(substituted)
        if m:
            if pattern is _MODEL_QUANTITY_PATTERN and _is_year_shaped_model_quantity(m.group(1)):
                continue
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None
