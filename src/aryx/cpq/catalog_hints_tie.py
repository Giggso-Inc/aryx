"""Tie-break for extract_catalog_hints when one option label is shared by
several real values of the SAME attribute.

Restores the module added in 9ca4f4db and removed in 05c3ecaa (both inside
PR #451). It was removed because it did not fire for the APX 900 case that PR
was chasing -- correctly, since that product has only ONE option under the
product selector. It does fire for the other half of the same catalog defect,
where one label maps to both a product's own code and a variant's.

Deliberately narrow, after review:

* Only the product selector (`catalog_profile.PRODUCT_LITERAL`). The evidence
  behind this rule was measured on that attribute alone (ws 1267: 28 tied
  labels, 26 resolvable). The same shape exists on other menu attributes --
  251 tied labels, 220 of them resolvable -- with no evidence that preferring
  the base value is right there. Any attribute added here should be measured
  first, the way the selector was.
* Not when the question also evidences a longer sibling code. "APX 8000"
  matches both the radio and its FLASHport variant; if the customer's wording
  also contains the rest of the variant's code, they may well mean the
  variant, so nothing is picked and the caller asks.

What goes in: the (variable_name, item_value) pairs a matched phrase could
select, the normalized phrase, and the normalized question. What comes out:
the single pair the phrase selects, or None to keep the caller's never-guess
path. No product, model or catalog name appears here -- the rule is "one
value's own code IS the typed phrase, and nothing contradicts it".
"""
from __future__ import annotations

from aryx.cpq.hint_normalization import _normalize_for_hint
from aryx.raven_log import raven_log, would_log


def _log_tie(selected: str, reason: str, entries: set[tuple[str, str]], exact: int) -> None:
    """Record which way a shared-label tie went, and why."""
    if not would_log("DEBUG"):
        return
    raven_log("DEBUG", "P4", "ask.catalog_hint.tie shared option label resolved or skipped", context={
        "selected_option": selected, "available_options": ["exact_code", "skip"],
        "reason_code": reason, "policy_version": "catalog_hint_tie_v2",
        "tied_values": len(entries), "exact_codes": exact,
        "variable_name": next(iter(entries))[0] if entries else ""})


def _variant_evidenced(entries: set[tuple[str, str]], phrase: str, question_norm: str) -> bool:
    """True when a longer sibling code extends the phrase and the question shows it.

    The matched phrase is a shared label, so a sibling whose own code starts
    with it is a more specific reading of the same words. When the rest of that
    sibling's code also appears in the question, the wording supports the
    variant and the tie must not be resolved to the base value.
    """
    for _vn, item_value in entries:
        code = _normalize_for_hint(item_value)
        if code == phrase or not code.startswith(phrase):
            continue
        remainder = code[len(phrase):]
        if remainder and remainder in question_norm:
            return True
    return False


def exact_code_owner(
    entries: set[tuple[str, str]], phrase: str, question_norm: str = "",
) -> tuple[str, str] | None:
    """Return the one (variable_name, item_value) whose own code IS the phrase.

    A label can be shared by several real values of one attribute: in a live
    catalog "APX 8000" is the display text of both the radio's own code and the
    FLASHport variant's, so the matched phrase alone cannot say which the
    customer meant. When exactly one of the tied values has an item_value that
    normalizes to the matched phrase itself, this prefers that value -- the
    customer's words name it exactly and nothing longer.

    Note this is a preference for the base value, not proof: the customer typed
    the shared label, and one value's code merely happens to equal it. The two
    guards below keep that preference honest.

    Args:
        entries: the distinct (variable_name, item_value) pairs sharing the phrase.
        phrase: the already-normalized phrase that matched the customer's text.
        question_norm: the normalized question, for the sibling-evidence guard.

    Returns:
        The single pair to select, or None when the tie must not be resolved.
    """
    exact = [e for e in entries if _normalize_for_hint(e[1]) == phrase]
    if len(exact) != 1:
        _log_tie("skip", "NO_EXACT_CODE" if not exact else "MULTIPLE_EXACT_CODES", entries, len(exact))
        return None
    if question_norm and _variant_evidenced(entries, phrase, question_norm):
        _log_tie("skip", "VARIANT_EVIDENCED_IN_TEXT", entries, len(exact))
        return None
    _log_tie("exact_code", "EXACT_CODE_MATCH", entries, len(exact))
    return exact[0]


def single_entry(
    entries: list[tuple[str, str]], phrase: str, question_norm: str = "",
) -> tuple[str, str] | None:
    """Return the one (variable_name, item_value) a matched phrase selects.

    One distinct pair: that pair, unchanged. Several genuinely different real
    values of the same attribute can share a phrase, and guessing between them
    is never acceptable -- except on the product selector, where
    `exact_code_owner` may prefer the value the wording names exactly. Every
    other attribute keeps the never-guess outcome, because the rule has not
    been measured there.

    Returns:
        The selected pair, or None when the caller must not hint anything.
    """
    distinct = set(entries)
    if len(distinct) == 1:
        return entries[0]
    from aryx.cpq.catalog_profile import PRODUCT_LITERAL  # lazy: avoids an import cycle
    if any(vn != PRODUCT_LITERAL for vn, _iv in distinct):
        _log_tie("skip", "NOT_PRODUCT_SELECTOR", distinct, 0)
        return None
    return exact_code_owner(distinct, phrase, question_norm)
