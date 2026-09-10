"""Unit/pluralization-tolerant option-matching helpers, split out of
`cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md — module-level helper extraction beyond the
8 previously-deferred methods, done purely to shrink engine.py further).
Re-exported from `aryx.cpq.engine` (see the import there) so every
existing `from aryx.cpq.engine import <name>` caller/test keeps working
unchanged. Logic unchanged from the original inline definitions.

Live bug this whole cluster fixes: a customer reply of "2 Yrs" (or "2
Years") never matched a catalog option displayed as "2 Year" — the
existing tiers require the option's exact display text to appear as a
literal whole word, and neither the trailing "s" (pluralization) nor the
"Yrs" abbreviation survives that literal check. Rather than hardcoding a
synonym table for every unit the catalog might use ("yr"/"yrs"->"year",
"mo"/"mos"->"month", ...), this compares tokens generically: a trailing
"s" is treated as an optional plural marker, and a short token is treated
as an abbreviation of a longer one when its letters appear, in order, as
at least half of the longer token's letters ("yr" -> "year", "yrs" ->
"years") — the same kind of ordered-subsequence test command-line tools
use for abbreviated flag matching, not a per-unit lookup table.
"""

from __future__ import annotations


def _singularize_token(token: str) -> str:
    """Strip a likely plural "s" — but never from a 1-2 letter token,
    where that would leave nothing meaningful (keeps "as", "is" untouched;
    "yrs" -> "yr" is exactly the short-form case this exists for)."""
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _is_ordered_abbreviation(short: str, long: str) -> bool:
    """True when `short`'s letters occur, in order, inside `long`, and
    `short` covers at least half of `long`'s length — generic enough to
    recognize "yr" as an abbreviation of "year" without knowing what a
    year is, while still rejecting coincidental one- or two-letter hits."""
    if not short or not long or len(short) >= len(long):
        return False
    remaining = iter(long)
    if not all(ch in remaining for ch in short):
        return False
    return len(short) >= max(2, len(long) // 2)


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def _tokens_match_loosely(a: str, b: str) -> bool:
    """Equal after optional de-pluralization, or one an ordered
    abbreviation of the other — except a token carrying a digit (a
    quantity, "2" vs "3", "5" vs "12") must match EXACTLY, never loosely.
    Without this, the ordered-subsequence check would itself treat "1" as
    an "abbreviation" of "12" and silently cross-match the wrong
    quantity — worse than merely being unit-unaware."""
    if a == b:
        return True
    if _has_digit(a) or _has_digit(b):
        return False
    na, nb = _singularize_token(a), _singularize_token(b)
    if na == nb:
        return True
    return _is_ordered_abbreviation(na, nb) or _is_ordered_abbreviation(nb, na)


def _option_matches_with_unit_normalization(display_name: str, ua: str) -> bool:
    """True when `display_name`'s tokens appear, in order and each loosely
    matching (see `_tokens_match_loosely`), as a contiguous run of tokens
    somewhere inside `ua` — e.g. "2 Year" inside "set smartprogramming to
    2 years", or standing alone as "2 yrs".

    Scoped to options that actually carry a quantity: `display_name` must
    contain at least one purely-numeric token, and that token must match
    verbatim in `ua` (enforced by `_tokens_match_loosely` above). Without
    this gate, the abbreviation heuristic alone is too permissive for a
    single-word option with no quantity at all — a catalog option
    displayed as "Android" would otherwise match a message containing the
    ordinary word "and" (`_is_ordered_abbreviation("and", "android")` is
    True on letters alone), and this repo's own catalogs use short
    product-line prefixes ("APX", "SAM"-style) where the same risk is not
    hypothetical. Requiring a quantity anchor keeps this tier scoped to
    exactly what it was built for: "<number> <unit>" options."""
    dn_tokens = display_name.strip().lower().split()
    if not any(_has_digit(t) for t in dn_tokens):
        return False
    ua_tokens = ua.strip().lower().split()
    n = len(dn_tokens)
    if n == 0 or n > len(ua_tokens):
        return False
    for start in range(len(ua_tokens) - n + 1):
        window = ua_tokens[start:start + n]
        if all(_tokens_match_loosely(u, d) for u, d in zip(window, dn_tokens)):
            return True
    return False
