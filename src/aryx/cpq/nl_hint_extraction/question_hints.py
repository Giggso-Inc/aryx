"""CPQ-intent detection and the generic NL hint sweep (Phase 4 step 11
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The two entry points that look at nothing but the raw question text plus
the workspace's own ingested product inventory: `is_cpq_question` (should
this turn route to CPQ at all?) and `extract_hints` (shortcut-pattern,
country and region candidates).

Module-level tables (`_CPQ_TRIGGER`, `_HINT_PATTERNS`, `_COUNTRY_PREP`,
`_REGION_PATTERNS`, `_HINT_MIN_PHRASE_LEN`) are read off the engine
MODULE object rather than imported by value, so the original bare-global
references -- and any patch of them -- resolve at call time exactly as
before. Collaborators (`ingested_product_alias_map`,
`_ingested_product_names`, `is_recognized_country`) are reached back
through the passed-in `engine` instance for the same reason.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq import engine as _engine_module


def is_cpq_question(
    engine: Any, question: str, reader: Any = None, workspace_id: int = 1,
) -> bool:
    """True when the question is a CPQ configuration / quote request.

    Two independent signals: the generic CPQ-vocabulary regex (fixed
    English words, not ingested data), OR a mention of any product
    actually ingested in this workspace (dynamic — same live-graph
    source as detect_product_mention). A question naming a product
    with no other CPQ-domain word (e.g. just "MOTOTRBO?") still routes
    to CPQ without needing that product's name hardcoded here.

    Live-confirmed gap (2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
    PLAN.md): the dynamic fallback used to check ONLY
    _ingested_product_names — internal BOM family codes
    ("aSTRO25_bom", "softwareSolutions_BOM"), never the real,
    customer-facing product name ("APX Next") a customer actually
    types. "I want to order APX Next radios..." named a real,
    ingested product by its real name and STILL fell through
    entirely to the generic non-CPQ pipeline. Switched to
    ingested_product_alias_map — the same catalog-tree-derived alias
    source detect_product_mention already relies on successfully,
    which carries both the family code AND every real product/line
    name from each catalog's own bm_catalog tree.
    """
    if _engine_module._CPQ_TRIGGER.search(question):
        return True
    if reader is None:
        return False
    q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
    if not q_norm:
        return False
    alias_map = engine.ingested_product_alias_map(reader, workspace_id)
    candidates = set(alias_map) | set(alias_map.values()) | set(
        engine._ingested_product_names(reader, workspace_id)
    )
    return any(
        len(norm) >= _engine_module._HINT_MIN_PHRASE_LEN and norm in q_norm
        for name in candidates
        if name
        for norm in (re.sub(r"[^a-z0-9]", "", name.lower()),)
    )


def extract_hints(engine: Any, question: str) -> dict[str, str]:
    """Extract attribute value hints from natural language.

    Returns {attr_key_fragment: hint_value} where hint_value is matched
    word-boundary against DB option display names — no hardcoded country list.

    Contract callers must honor for `hints["country"]` specifically
    (review finding, docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md):
    this is a raw, UNVALIDATED regex candidate, not a confirmed country.
    When no `_COUNTRY_PREP` match in the sentence is a real, recognized
    country, this still returns the leftmost match anyway (so a caller
    that wants to reject explicitly has something to reject, rather than
    a silent absence indistinguishable from "no country mentioned at
    all"). Every caller MUST re-validate via `is_recognized_country`
    before trusting this value for anything — never assign it to
    `session.country` (or equivalent) directly. Both current callers
    (`ask_api.py`'s turn-1 hint block and `_mine_history_for_cpq_
    context`) already do this; a new caller that reads `hints.get(
    "country")` without the same check would silently reintroduce the
    exact bug class this whole plan closes.
    """
    hints: dict[str, str] = {}

    # Specific shortcut patterns — first match wins per key; more specific
    # patterns must be listed first in _HINT_PATTERNS (see ordering comment there).
    for key, pattern, value in _engine_module._HINT_PATTERNS:
        if key not in hints and re.search(pattern, question, re.IGNORECASE):
            hints[key] = value

    # Generic country extraction: "customer in Australia", "located in New Zealand"
    # Captures the proper-noun after a preposition and matches it against DB display names.
    #
    # Tries every match in the sentence, not just the first -- fallback-
    # path hardening, 2026-08-13 (docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_
    # 08_13.md review finding). `re.search` only ever returns the
    # LEFTMOST match; a bogus earlier trigger ("for APX Next" -> "AP")
    # used to shadow a real, later, correctly-stated country in the
    # same sentence ("...in the United States") because nothing ever
    # looked past the first hit. Prefers the first candidate that's a
    # real, recognized country; falls back to the plain leftmost match
    # (this method's original behavior) only when NONE of them
    # validate, so callers that intend to validate downstream
    # themselves still get a candidate to reject, not a silent None.
    if "country" not in hints:
        valid_match = None
        first_match = None
        for m in _engine_module._COUNTRY_PREP.finditer(question):
            candidate = m.group(1).strip().title()
            if first_match is None:
                first_match = candidate
            if engine.is_recognized_country(candidate):
                valid_match = candidate
                break
        if valid_match is not None:
            hints["country"] = valid_match
        elif first_match is not None:
            hints["country"] = first_match

    # Region hints (abbreviations)
    if "region" not in hints:
        for pattern, value in _engine_module._REGION_PATTERNS:
            if re.search(pattern, question, re.IGNORECASE):
                hints["region"] = value
                break

    return hints
