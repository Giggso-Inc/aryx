"""Tie-break for extract_catalog_hints when one option label is shared by
several real values of the same attribute.

Restores the module added in 9ca4f4db and removed in 05c3ecaa (both inside
PR #451). It was removed because it did not fire for the APX 900 case that PR
was chasing -- correctly, since that product has only ONE option under the
product selector. It does fire for the other half of the same catalog defect,
where a label maps to both a product's own code and a variant's: confirmed
live (ws 1267, 2026-10-07) on 26 of the 28 tied labels, the APX 8000 family
among them. Those 26 previously hinted nothing, so the model leaf stayed
ambiguous and the customer was shown every product in the family.

What goes in: the (variable_name, item_value) pairs a matched phrase could
select, plus the normalized phrase itself. What comes out: the single pair the
phrase unambiguously selects, or None to keep the caller's never-guess path.
No product, model or catalog name appears here -- the rule is "one value's own
code IS what the customer typed", which is data, not a literal.
"""
from __future__ import annotations

from aryx.cpq.hint_normalization import _normalize_for_hint
from aryx.raven_log import raven_log, would_log


def exact_code_owner(
    entries: set[tuple[str, str]], phrase: str,
) -> tuple[str, str] | None:
    """Return the one (variable_name, item_value) whose own code IS the phrase.

    A label can be shared by several real values of one attribute: in a live
    catalog "APX 8000" is the display text of both the radio's own code and
    the FLASHport variant's, so the matched phrase alone cannot say which the
    customer meant. When exactly one of the tied values has an item_value that
    normalizes to the matched phrase itself, the customer typed that value's
    own code and no guessing is involved. Zero or two-or-more such values keep
    the never-guess outcome.

    Args:
        entries: the distinct (variable_name, item_value) pairs sharing the phrase.
        phrase: the already-normalized phrase that matched the customer's text.

    Returns:
        The single unambiguous pair, or None when the tie cannot be resolved.
    """
    exact = [e for e in entries if _normalize_for_hint(e[1]) == phrase]
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.catalog_hint.tie shared option label resolved or skipped", context={
            "selected_option": "exact_code" if len(exact) == 1 else "skip",
            "available_options": ["exact_code", "skip"],
            "reason_code": "EXACT_CODE_MATCH" if len(exact) == 1 else (
                "NO_EXACT_CODE" if not exact else "MULTIPLE_EXACT_CODES"),
            "policy_version": "catalog_hint_tie_v1",
            "tied_values": len(entries), "exact_codes": len(exact),
            "variable_name": next(iter(entries))[0] if entries else ""})
    return exact[0] if len(exact) == 1 else None


def single_entry(
    entries: list[tuple[str, str]], phrase: str,
) -> tuple[str, str] | None:
    """Return the one (variable_name, item_value) a matched phrase selects.

    One distinct pair: that pair. Several genuinely different real values of
    the same attribute can share a phrase (a variant suffix shared by sibling
    products, for example), and guessing between them is never acceptable --
    unless exactly one value's own code IS the phrase, which `exact_code_owner`
    decides.

    Returns:
        The selected pair, or None when the caller must not hint anything.
    """
    distinct = set(entries)
    if len(distinct) == 1:
        return entries[0]
    return exact_code_owner(distinct, phrase)
