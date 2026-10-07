"""Tie-break for extract_catalog_hints when one option label is shared by
several real values of the same attribute (see exact_code_owner).
"""
from __future__ import annotations

from aryx.cpq import engine as _engine_module
from aryx.raven_log import raven_log, would_log


def exact_code_owner(
    entries: set[tuple[str, str]], phrase: str,
) -> tuple[str, str] | None:
    """The one (variable_name, item_value) whose own code IS the phrase.

    A label can be shared by several real values of one attr: in
    Astro25Configdata both APX900 and APX900FLASHPORT display as "APX 900"
    (ws 1267, 2026-10-07), so "I want a quote for APX 900" hinted nothing
    and Product was asked with ~300 options. When exactly one of the tied
    values has an item_value that normalizes to the matched phrase itself,
    the customer typed that product's own code -- not a guess. Zero or 2+
    such values keep the never-guess outcome (None).
    """
    exact = [e for e in entries if _engine_module._normalize_for_hint(e[1]) == phrase]
    if would_log("DEBUG"):
        _log_tie(entries, exact)
    return exact[0] if len(exact) == 1 else None


def _log_tie(entries: set[tuple[str, str]], exact: list[tuple[str, str]]) -> None:
    """DEBUG decision record for one same-attr tie (counts only)."""
    raven_log("DEBUG", "P4", "ask.catalog_hint.tie shared option label resolved or skipped", context={
        "selected_option": "exact_code" if len(exact) == 1 else "skip",
        "available_options": ["exact_code", "skip"],
        "reason_code": "EXACT_CODE_MATCH" if len(exact) == 1 else (
            "NO_EXACT_CODE" if not exact else "MULTIPLE_EXACT_CODES"),
        "tied_values": len(entries), "exact_codes": len(exact),
        "variable_name": next(iter(entries))[0]})


def single_entry(
    entries: list[tuple[str, str]], phrase: str,
) -> tuple[str, str] | None:
    """The one (variable_name, item_value) a matched phrase selects, or None.

    Same attr, but 2+ genuinely different real values can share a phrase
    (e.g. a "(4G LTE+5G)" variant suffix shared by sibling products "APX
    NEXT"/"APX NEXT XE", once _parenthetical_suffix contributes candidate
    text). Never guess which one the customer meant -- unless exactly one
    value's own code IS the phrase (exact_code_owner).
    """
    distinct = set(entries)
    if len(distinct) == 1:
        return entries[0]
    return exact_code_owner(distinct, phrase)
