"""Turn-level quantity-mention detection and precheck, split out of
`cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction beyond
the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq.quantity.quantity_hint_extraction import extract_quantity_decimal_hint, extract_quantity_hint
from aryx.cpq.state import ConfigAttr


# Any mention of the word "quantity"/"qty"/"how many" at all -- the cheap,
# deterministic pre-filter for even bothering to consider quantity routing.
# Purely a "is it worth looking at this turn at all" gate, not a judgment
# call -- the actual product-vs-catalog-attribute disambiguation (a real
# judgment call, not something a keyword list can reliably make) is an LLM
# decision, made in ask_api.py's _llm_resolve_quantity_target, mirroring
# this file's other single-purpose LLM helpers rather than the big
# generic intent gateway (whose schema has no way to represent "the
# overall product quantity" at all -- it only ever names real ConfigAttr
# variable_names). docs/CPQ_QUANTITY_TARGET_MISROUTE_FIX_PLAN_2026_08_17.md:
# that prompt is reinforced with each candidate's filled_source
# provenance and explicit anti-digit-coincidence guidance, rather than
# routing this decision through pattern-matching instead.
_QUANTITY_WORD_RE = re.compile(r"(?i:\bqty\b|\bquantity\b|\bhow\s+many\b)")
# "change/set/update the quantity to N" vs. a plain question ("what's my
# quantity") -- deterministic, not a judgment call: these are unambiguous
# verb cues, unlike WHICH quantity is meant.
_QUANTITY_CHANGE_VERB_RE = re.compile(
    r"(?i:\b(?:change|set|update|make\s+it|adjust)\b)"
)


def question_mentions_quantity(question: str) -> bool:
    """Cheap, regex-only pre-check: is this turn even worth loading the
    catalog for to consider quantity routing? Callers must check this
    BEFORE loading attrs -- loading the full product config on every
    single turn regardless of content is wasteful and, in a caller with a
    test-double reader, can fail for reasons unrelated to quantity at all.
    """
    return bool(_QUANTITY_WORD_RE.search(question))


def find_catalog_quantity_attrs(attrs: list[ConfigAttr]) -> list[ConfigAttr]:
    """Real catalog attributes shaped like a per-item quantity field: no
    catalog menu (a genuine free-text/numeric attribute), select_type
    integer/float, and "quantity" or "qty" in the display label or variable
    name -- e.g. "Quantity (VX650 Item Type)". These are never asked
    proactively (the session-level product_quantity is), but stay
    reachable when the customer names one directly or picks one via
    disambiguation.
    """
    out = []
    for a in attrs:
        if a.options:
            continue
        if a.select_type not in ("integer", "float"):
            continue
        haystack = f"{a.display_label} {a.variable_name}".lower()
        if "quantity" in haystack or "qty" in haystack:
            out.append(a)
    return out


def quantity_turn_precheck(question: str, attrs: list[ConfigAttr]) -> dict[str, Any] | None:
    """Cheap, deterministic first pass for a quantity-related turn -- None
    when the message isn't about quantity at all (caller falls through to
    normal handling). Otherwise returns the facts the caller needs to
    decide routing:
      {"is_change": bool, "value": int | None, "decimal_value": str | None,
       "candidates": list[ConfigAttr]}

    `decimal_value` (PR #186 review, medium) is set when the message
    stated a decimal quantity ("change quantity to 10.0") -- `value`
    stays None for these (a decimal is never a valid quantity), but
    `is_change` is still True so the caller can reject with a message
    quoting the real decimal text instead of silently doing nothing.

    Deliberately does NOT decide "which quantity does the customer mean" --
    that's a real judgment call once `candidates` is non-empty, made by an
    LLM (ask_api._llm_resolve_quantity_target), not a keyword heuristic
    (docs/CPQ_QUANTITY_SLOTFILLING_AND_UI_ISSUES_PLAN_2026_08_11.md step 3).
    """
    if not _QUANTITY_WORD_RE.search(question):
        return None
    value = extract_quantity_hint(question)
    decimal_value = extract_quantity_decimal_hint(question)
    _has_change_verb = bool(_QUANTITY_CHANGE_VERB_RE.search(question))
    return {
        "is_change": _has_change_verb
        and (value is not None or decimal_value is not None),
        # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
        # 23: exposed separately from `is_change` so a caller can tell
        # "explicit change verb, but nothing parseable at all" ("change
        # quantity to a couple dozen") apart from "not a change attempt
        # in the first place" -- the former is exactly the case an LLM
        # extraction fallback should be tried for; the latter never
        # should be.
        "has_change_verb": _has_change_verb,
        "value": value,
        "decimal_value": decimal_value,
        "candidates": find_catalog_quantity_attrs(attrs),
    }
