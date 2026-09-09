"""STEP 1 — sequential anchor prompting for the product family, split
out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Only runs while
`session.product_name` is unset; hwVersion is no longer an anchor (D1)
— it resolves through the normal rule cascade once product+country are
known. Logic unchanged from the original inline `if` block; the "no
detection -> ask which family" tail lives in the sibling `ask_step1_
product_family_prompt.py` purely to keep this file under the line cap.
`_cpq_engine`, `logger`, `_handle_cpq_qa`, `_resolve_scope_reply`,
`_build_scope_skip_response`, `_build_scope_family_only_response`, and
`_scoped_reask_response` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path, and the latter four aren't yet
split out of ask_api.py.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_scope_reask_responses import _build_scope_family_only_response, _build_scope_skip_response, _resolve_scope_reply, _scoped_reask_response
from aryx.api import ask_handle_cpq_qa as _ask_handle_cpq_qa_module
from aryx.api.ask_turn_steps.ask_step1_product_family_prompt import _build_product_family_prompt_or_resolve
from aryx.cpq.pending_scope import clear_pending_scope, resolve_against_scope


def _step1_resolve_product_anchor(
    req: "Any", session: Any, reader: Any, hints: dict,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn is fully handled by the
    product-anchor gate; None once `session.product_name` is anchored
    (freshly this turn, or already set before this call), in which case
    the caller proceeds to STEP 2 for the resolved product's catalog.
    """
    from aryx.api import ask_api as _ask_api_module
    if session.product_name:
        return None
    _cpq_engine = _ask_api_module._cpq_engine
    _step1_t0 = time.monotonic()
    _ask_api_module.logger.info("cpq_step: step1_anchor_gate start run_id=%s", session.run_id)
    # Intent-first gate (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 1): check
    # whether this message reads as a genuine question BEFORE trusting
    # any anchor-detection result at all — not just in the blind-accept
    # fallback below. Confirmed live this needed to run first, not
    # second: detect_product_mention itself matched a fuzzy incidental
    # mention inside a question, not the user's actual intent — so
    # gating only on "detection failed" was never going to catch this
    # case. Routes to the same graph-grounded Q&A path (_handle_cpq_qa)
    # used everywhere else in this file — attrs=[] is safe here since no
    # product/catalog is chosen yet, and _handle_cpq_qa's generic graph
    # search doesn't require it.
    if (
        session.pending_anchor == "product"
        and _cpq_engine.detect_qa_question(req.question, None, strict=True)
    ):
        _ask_api_module.logger.info(
            "cpq_intent_gate: question-shaped message %r intercepted "
            "before product-anchor detection (turn=%s) -> routing to Q&A",
            req.question, session.turn,
        )
        return _ask_handle_cpq_qa_module._handle_cpq_qa(req, session, [], reader, resume_review=False)
    # PROMPT 7: reply to a prior "did you mean" / family list first
    detected = ""
    _fresh_detection_tried = False
    if session.pending_scope_candidates and session.pending_scope_kind in (
        "product_suggestions", "family_disambiguation", "",
    ):
        _scope_cands0 = list(session.pending_scope_candidates)
        _sres0 = _resolve_scope_reply(
            req.question, _scope_cands0, "product family",
            session, req.workspace_id,
        )
        if _sres0 == "skip":
            return _build_scope_skip_response(
                req, session, _scope_cands0, "product family",
            )
        if _sres0 == "family_only":
            return _build_scope_family_only_response(
                req, session, _scope_cands0, "product family",
            )
        if _sres0.matched:
            detected = _sres0.matched
            clear_pending_scope(session)
        else:
            # A weak/"miss"-tier match against the STALE candidate list
            # must never outrank a confident, independent detection on
            # this new message — otherwise one bad "did you mean" reply
            # traps the session repeating it forever. Only fall back to
            # the stale-scope reask when this fresh, full-catalog
            # detection ALSO finds nothing. _fresh_detection_tried
            # guards the identical call below (Raven review M1) against
            # detect_product_mention's own double graph+RDB fetch.
            detected = _cpq_engine.detect_product_mention(
                req.question, hints, reader, req.workspace_id,
            )
            _fresh_detection_tried = True
            if detected:
                clear_pending_scope(session)
            elif _sres0.suggestions:
                return _scoped_reask_response(
                    req, session, req.question,
                    scope_label="product family",
                    tools_called="cpq_product_did_you_mean()",
                )
    if not detected and not _fresh_detection_tried:
        detected = _cpq_engine.detect_product_mention(
            req.question, hints, reader, req.workspace_id,
        )
    if not detected and session.pending_anchor == "product":
        # Only blind-accept raw text when it resolves via scope ladder
        # against known families — never invent a product name.
        _fams = _cpq_engine.list_ingested_families(reader, req.workspace_id)
        if _fams:
            _sraw = resolve_against_scope(req.question, list(_fams))
            if _sraw.matched:
                detected = _sraw.matched
    if not detected:
        # Priority 2: resolve against real ingested catalog/family/
        # product-option data instead of accepting raw text
        # unconditionally — closes two gaps: unpatterned products
        # resolve with zero hardcoded entries, and a reply to the "what
        # family?" prompt below is validated the same way instead of
        # being accepted verbatim (a bare "US" must never become
        # product_name = "US").
        match = _cpq_engine.resolve_product_hint(reader, req.workspace_id, req.question)
        if match:
            detected = match[1]
    if not detected:
        _response, detected = _build_product_family_prompt_or_resolve(req, session, reader)
        if _response is not None:
            return _response
    session.product_name = detected
    # Keep the longer order utterance (often has country + customer) when
    # this turn is only a short family reply (e.g. "aSTRO25_bom") — N1 /
    # country-once: overwriting with the short reply made the later
    # country gate blind to the original "destination country United States".
    prior_anchor = session.product_anchor_question or ""
    if (
        not prior_anchor
        or len(req.question.strip()) >= len(prior_anchor.strip())
        or "country" in _cpq_engine.extract_hints(req.question)
    ):
        session.product_anchor_question = req.question
    _ask_api_module.logger.info(
        "cpq_switch: product anchored turn=%s product=%r", session.turn, detected,
    )
    _ask_api_module.logger.info(
        "cpq_step: step1_anchor_gate done run_id=%s elapsed_s=%.3f",
        session.run_id, time.monotonic() - _step1_t0,
    )
    return None
