"""Building the "which product family?" disambiguation prompt (or
auto-resolving via a single strong fuzzy suggestion) when STEP 1's
product-anchor detection ladder found nothing, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling
`ask_step1_product_anchor.py` under the line cap. Logic unchanged from
the original inline block. `_cpq_engine` and `_persist_cpq_history` are
read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.pending_scope.pending_scope import format_did_you_mean, resolve_against_scope, set_pending_scope


def _build_product_family_prompt_or_resolve(
    req: "Any", session: Any, reader: Any,
) -> "tuple[dict[str, Any] | None, str]":
    """Returns (response_dict, detected) — `response_dict` is non-None
    when this turn is fully handled (a "did you mean" prompt or the
    generic "need product family" ask); `detected` carries an
    auto-resolved product name (via a single strong fuzzy suggestion or
    scope-fuzzy family match) when the caller should fall through and
    anchor to it instead.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    session.pending_anchor = "product"
    families = _cpq_engine.list_ingested_families(reader, req.workspace_id)
    # PROMPT 7: pet names / typos ("Asr"/"asty") → did you mean, with
    # pending_scope so the next reply is matched in-scope.
    _alias = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
    suggestions = _cpq_engine.suggest_product_candidates(
        req.question, reader, req.workspace_id, limit=5, alias_map=_alias,
    )
    detected = ""
    # Also allow prefix / in-scope fuzzy against family names for short
    # nicknames that fall below the mid-band threshold — but ONLY for a
    # short, nickname-shaped reply (the documented intent above).
    # resolve_against_scope's own fuzzy tier has no sliding window for a
    # candidate SHORTER than the query (it falls straight to a raw
    # whole-string ratio), so running it against a full, ordinary
    # sentence scores an unrelated short family name via pure character-
    # overlap coincidence — confirmed live: "I need a quote for some
    # radios" "matched" MOTOTRBO with zero real signal. Gating on word
    # count keeps the genuine nickname case working while a long,
    # clearly generic message falls through to the all-families "did
    # you mean...?" prompt below instead of a fabricated guess.
    if not suggestions and families and len(req.question.strip().split()) <= 4:
        _sres = resolve_against_scope(req.question, list(families))
        if _sres.matched:
            detected = _sres.matched
        elif _sres.suggestions:
            suggestions = list(_sres.suggestions)
    if detected:
        return None, detected  # fall through to anchor with fuzzy family match
    if len(suggestions) == 1:
        # Live-confirmed gap (2026-08-27, "quote for SVX" / "quote SVX" /
        # "SVX quote"): resolve_product_hint doesn't score a bare short
        # nickname confidently enough on its own, but suggest_product_
        # candidates's fuzzy "maybe" band finds exactly ONE real ingested
        # family it could plausibly mean -- there is nothing else in the
        # catalog for it to be confused with. Asking "did you mean X?"
        # here only wastes a turn on an answer that was never actually in
        # doubt. Same "a single real candidate isn't ambiguity" principle
        # already trusted elsewhere in this codebase (auto_fill's single-
        # remaining-option fallback, _label_collision_for's requires-
        # pending guard) -- deliberately scoped to exactly one
        # suggestion; 2+ still falls through to the real "did you
        # mean...?" prompt below, where genuine ambiguity remains.
        return None, suggestions[0]
    if suggestions:
        set_pending_scope(
            session,
            kind="product_suggestions",
            candidates=list(suggestions),
            origin_question=req.question,
            attr_vn="",
            asked_turn=session.turn,
        )
        answer = format_did_you_mean(
            req.question, suggestions, scope_label="product family",
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_product_did_you_mean()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }, ""
    # No fuzzy/mid-band signal at all (a truly generic message, e.g. "I
    # need a quote for some radios") — rather than a soft "please provide
    # the product family" instruction that names the options only as an
    # aside, ask the SAME direct "did you mean A, or B?" question used
    # everywhere else a choice needs disambiguating (format_did_you_mean),
    # so a small (e.g. two-product) workspace always reads as an explicit
    # choice between the real ingested names, never a generic ask-again
    # prompt. Falls back to the old instructive phrasing only when
    # NOTHING is ingested yet — format_did_you_mean requires at least one
    # real candidate.
    if families:
        set_pending_scope(
            session,
            kind="product_suggestions",
            candidates=list(families),
            origin_question=req.question,
            attr_vn="",
            asked_turn=session.turn,
        )
        answer = format_did_you_mean(
            req.question, list(families), scope_label="product family",
        )
    else:
        answer = (
            f"To start the configuration I need the **product family** "
            f"(e.g., *APX Next*, *MOTOTRBO*, *SL3500e*). Could you provide that?"
        )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_anchor_validation()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }, ""
