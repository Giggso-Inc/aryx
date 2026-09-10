"""Product mention detection from NL text (Phase 4 step 11 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`detect_product_mention` is the confirm-worthy half of the product
anchor: exact longest-first alias match, then the fuzzy fallback, over
`ingested_product_alias_map`'s catalog-tree aliases.
`suggest_product_candidates` (the lower "maybe" band) lives in
`product_suggestions` -- same alias inventory, same scoring, different
threshold.

`_PRODUCT_FUZZY_MATCH_THRESHOLD` is read off the engine MODULE object;
the alias map and both scoring helpers go back through the passed-in
`engine` instance so their patches still apply.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq import engine as _engine_module


def detect_product_mention(
    engine: Any, question: str, hints: dict[str, str],
    reader: Any = None, workspace_id: int = 1,
    alias_map: dict[str, str] | None = None,
) -> str:
    """Best-effort product display label from NL text, or "" if none found.

    Dynamic — no hardcoded product list. Matches against the REAL
    product/family names of every catalog actually ingested into this
    workspace (via _ingested_product_names), so a newly-ingested product
    line is recognised immediately without a code change. Falls back to
    the NL-hint-derived "product" key, then "" (Step 1's normal
    anchor-prompt path takes over when nothing resolves).

    D1 (CPQ_CASCADE_CONVERSATION_PLAN.md §2): the anchor gate is now
    sequential (product, then country) rather than a single-shot block
    requiring product+line+country together — hwVersion (formerly the
    "product line" anchor) resolves through the normal rule cascade
    instead, like any other dependent variable.

    Candidates are tried LONGEST-first (mirrors extract_catalog_hints'
    "longer/more specific option text is tried first so a short phrase
    can't shadow a longer, more specific one"): a workspace can ingest
    both a generic family name ("APX NEXT") and a specific variant
    ("APX NEXT XE") as separate catalog entities, in no guaranteed
    order from the graph — without this ordering, a customer asking
    about "APX NEXT XE" could silently anchor to the generic "APX NEXT"
    depending on which entity the graph happened to return first
    (regression caught in review: this is the same "variant must win
    over generic" guarantee the old hardcoded _PRODUCT_PATTERNS table
    enforced via explicit list ordering).

    Falls back to a FUZZY substring match (deterministic, no LLM) when
    no candidate is an exact substring of the question — catches a
    partial/incomplete mention ("SL 3500" missing the trailing "e") or
    a typo, cases the exact check silently misses, which previously
    left a mid-session product switch undetected with no signal
    anything was wrong. Reuses aryx.resolution.classical.string_score
    (SequenceMatcher-based), the same deterministic scoring already
    used for entity-resolution matching elsewhere in this codebase —
    no new dependency, no network call, no non-determinism. Slides a
    window the length of each candidate's normalized name across the
    normalized question and keeps the best score seen; only a name at
    least _HINT_MIN_PHRASE_LEN chars long is ever considered, same
    guard used elsewhere in this module to stop short names from
    spuriously matching unrelated text. This is purely a widened
    DETECTION signal — the caller (ask_api.py's confirm_switch gate)
    still requires explicit confirmation before anything is reset, so
    a fuzzy false positive costs one extra yes/no turn, never a silent
    wrong-product answer or data loss.

    Matching runs over ingested_product_alias_map's ALIASES (family
    names PLUS each catalog's own bm_catalog tree names — "APX™ NEXT",
    "vX650_BOM", ...) and resolves the matched alias to its owning
    FAMILY name (see that method's docstring for why the tree, not the
    flat product menu, is the only catalog-discriminating signal).
    Both XMLs carry the identical flat product list, so a raw product
    mention can never pick a catalog — the tree names can (confirmed
    live: "Quote APX Next Enhanced radios" matched nothing when only
    the two family identifiers were candidates).

    alias_map — pre-fetched ingested_product_alias_map result. Pass it
    when the caller also needs it for suggest_product_candidates in
    the same turn (review finding P2: the common no-match path loaded
    the same inventory twice through graph+RDB queries). When None,
    self-fetches as before.
    """
    q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
    if alias_map is None and reader is not None and q_norm:
        alias_map = engine.ingested_product_alias_map(reader, workspace_id)
    if alias_map and q_norm:
        ordered = sorted(
            ((name, re.sub(r"[^a-z0-9]", "", name.lower())) for name in alias_map),
            key=lambda t: len(t[1]), reverse=True,
        )
        for name, name_norm in ordered:
            if name_norm and name_norm in q_norm:
                return alias_map[name]
        scored = engine._fuzzy_score_candidates(
            q_norm, ordered, question_tokens=engine._question_tokens(question),
        )
        if scored and scored[0][1] >= _engine_module._PRODUCT_FUZZY_MATCH_THRESHOLD:
            return alias_map[scored[0][0]]
    return next((v for k, v in hints.items() if "product" in k), "")
