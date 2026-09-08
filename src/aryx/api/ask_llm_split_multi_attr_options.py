"""LLM-first check for a compound multi-attribute options question,
split out of `api/ask_api.py` (Phase 6/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline definition.
"""

from __future__ import annotations

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core
from aryx.api.ask_relevant_intent_candidates import _relevant_intent_candidates


def _llm_split_multi_attr_options_query(
    question: str, attrs: list, workspace_id: int,
) -> list[str] | None:
    """LLM-first check: does this options-query ask about 2+ genuinely
    DIFFERENT attributes at once (docs/config_consistency_issues_2026-07-30.md
    issue 3)?

    "what are the Frequency Bands and Wireless Carrier available?" must
    answer BOTH — `detect_attr_query` only ever returns a single best
    match, and (before the `detect_label_collision` grouping fix,
    engine.py) this exact question was wrongly treated as a single 3-way
    label collision even though "Wireless Carrier" shares zero tokens
    with "Frequency Bands" and isn't ambiguous at all. Those are two
    different bugs: a genuine label collision needs disambiguation
    (unchanged, still handled first); a compound multi-attribute mention
    needs BOTH answered, never a pick-one prompt.

    LLM-first rather than pure label-substring matching so this also
    catches paraphrased/synonym attribute mentions a literal-label check
    would miss — same "don't guess with a fragile heuristic" reasoning
    that moved earlier compound-detection work in this codebase
    (_llm_split_compound_change_and_question) off deterministic splitting.

    Scoped to `_relevant_intent_candidates`' own word-overlap narrowing
    (fallback_to_full=False — if NOTHING plausibly overlaps, there's
    nothing to split) so the prompt stays bounded on large catalogs and
    this never even calls the LLM for an unrelated question. Returns None
    when fewer than 2 real candidates overlap, or when the LLM's own
    judgment says this isn't genuinely a multi-attribute question —
    caller falls through to the existing single-attr fast path unchanged.
    """
    candidates = _relevant_intent_candidates(question, attrs, fallback_to_full=False)
    if len(candidates) < 2:
        return None
    catalog_lines = "\n".join(
        f"- \"{a.display_label}\" (variable_name={a.variable_name})"
        for a in candidates
    )
    sys = (
        "A customer asked a product-configuration assistant about the "
        "available options for one or more attributes. Determine whether "
        "the question asks about TWO OR MORE genuinely DIFFERENT "
        "attributes from the CANDIDATE list below — not one attribute "
        "whose own label happens to be ambiguous or shared by several "
        "catalog entries (that is a separate disambiguation concern, not "
        "a multi-attribute question). If it names 2+ different "
        "attributes, split it into that many self-contained per-attribute "
        "questions, each rephrased in the customer's own words. Never "
        "invent an attribute that isn't named in the message."
    )
    user = (
        f"CANDIDATE ATTRIBUTES:\n{catalog_lines}\n\n"
        f"MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"is_multi_attr": true|false, '
        '"questions": ["<self-contained question 1>", "<question 2>", ...]}'
    )

    def _validate(parsed: dict) -> list[str] | None:
        if not parsed.get("is_multi_attr"):
            return None
        raw_qs = parsed.get("questions") or []
        qs = [q.strip() for q in raw_qs if isinstance(q, str) and q.strip()]
        return qs if len(qs) >= 2 else None

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)
