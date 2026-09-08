"""Narrow LLM extraction fallbacks for a stated quantity the
deterministic extractor can't parse, and a bare country reply the alias
table can't resolve, split out of `ask_api.py` (final sweep, Phase
11/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md — docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.
md row 23 / docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md
ISSUE-007 Path B). `_llm_extract_quantity` only replaces the extraction
step, never the validation step — the caller MUST still run the result
through `is_valid_product_quantity`. `_llm_resolve_bare_country_reply`
catches genuine misspellings the alias table could never statically
enumerate, and never trusts the LLM's own spelling blindly — it runs
the result back through the SAME alias-group validation every other
path uses. Both reject-on-any-failure (parse error, timeout, exception)
rather than ever guessing. Logic unchanged from the original inline
definitions. `_llm_classify_intent_core` is read through the ask_api
module object (not imported by name) since tests patch several ask_api
names by dotted path.
"""

from __future__ import annotations

from aryx.cpq.engine import CpqEngine

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core


def _llm_extract_quantity(question: str, workspace_id: int) -> int | None:
    """Narrow extraction fallback for a stated quantity `extract_
    quantity_hint`'s regex/word-number patterns can't parse at all —
    tried only when the caller has already confirmed the message has an
    explicit quantity-change verb AND the deterministic extractor found
    neither an integer nor a decimal at all.
    """
    sys = (
        "A customer stated a quantity for a product order in a way that "
        "doesn't use plain digits or simple number words. Extract the "
        "integer quantity they mean, if any is genuinely stated "
        "(\"a couple dozen\" = 24, \"half a gross\" = 72). If no specific "
        "quantity is actually stated, say so — never guess a number that "
        "isn't really there."
    )
    user = (
        f"USER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"quantity": <integer> | null}'
    )

    def _validate(parsed: dict) -> int | None:
        val = parsed.get("quantity")
        if not isinstance(val, int) or isinstance(val, bool):
            return None
        return val

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)


def _llm_resolve_bare_country_reply(question: str, workspace_id: int) -> str | None:
    """Narrow last-resort escalation for Path B of ISSUE-007: a bare
    reply to the "what's the destination country?" anchor question that
    the deterministic, free alias-table lookup could NOT resolve.
    Returns the country's plain common name, or None when the text isn't
    recognizable as any real country at all — the caller falls back to
    the existing honest re-ask, never a guess.
    """
    sys = (
        "A customer was asked \"what's the destination country?\" and "
        "gave a short reply that a deterministic lookup table couldn't "
        "match to any of the world's real countries — most likely "
        "because they misspelled it. Identify which real country (if "
        "any) they most plausibly meant, and reply with its plain common "
        "name (e.g. \"United States\", \"Germany\", \"South Korea\"). If "
        "the reply doesn't plausibly name any real country at all (a "
        "fictional place, an unrelated word, gibberish), say so — never "
        "guess a country that isn't genuinely what they meant."
    )
    user = (
        f"CUSTOMER REPLY: {question}\n\n"
        'Reply ONLY as JSON: {"country": <plain common name string> | null}'
    )

    def _validate(parsed: dict) -> str | None:
        val = parsed.get("country")
        if not isinstance(val, str) or not val.strip():
            return None
        # Never trust the LLM's own spelling of the name blindly — run it
        # back through the SAME alias-group validation every other path
        # uses, so a hallucinated non-country string still can't slip
        # through this escalation step.
        return CpqEngine.is_recognized_country(val)

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)
