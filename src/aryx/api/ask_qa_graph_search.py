"""Generic graph-search Q&A fallback, split out of `_handle_cpq_qa`
(Phase 8/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_cpq_qa.py`
under the line cap. Logic unchanged from the original inline try/except
block. `logger`, `get_settings`, and `_synthesise`/`_extract_terms`/
`_enrich_with_attributes` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.cpq.intent_schema import Confidence, IntentCategory


def _qa_graph_search(
    req: "Any", session: Any, attrs: list, reader: Any,
    meta_result: Any, meta_prompt_tokens: int, meta_completion_tokens: int,
) -> "tuple[str, tuple[int, int, int, int, int, int]]":
    """Generic graph-search Q&A fallback, reached only when neither the
    fast attribute-options path nor the whole-catalog-enumeration path
    answered the question. Returns (qa_answer, (p_in, p_out, p_ms, s_in,
    s_out, s_ms)).
    """
    types = _ask_api_module.all_types(reader)
    try:
        terms, p_in, p_out, p_ms = _ask_api_module._extract_terms(
            req.question, types, req.history, workspace_id=req.workspace_id,
        )
        entities, calls = _ask_api_module.gather(reader, terms)
        # Two ingested product catalogs can share one workspace (e.g. an
        # APX Next export and an SL3500e export). When the fast path
        # above didn't resolve the question to one attribute, this
        # generic graph search has no attribute list to scope it, so it
        # can otherwise return nodes from BOTH catalogs for a name that
        # happens to appear in each (confirmed live: "carry solutions"
        # matched a menu item in both catalogs at once). Restrict to the
        # active session's catalog whenever one is known.
        catalog_prefix = attrs[0].catalog_prefix if attrs else ""
        if catalog_prefix:
            entities = [e for e in entities if e.type.startswith(catalog_prefix)]
            for e in entities:
                e.neighbors = [
                    n for n in e.neighbors
                    if n.get("type", "").startswith(catalog_prefix)
                ]
        entities = _ask_api_module._enrich_with_attributes(entities, req.workspace_id)
        context = _ask_api_module.render_context(entities)
        # Session values (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 3):
        # entities found here come from the STATIC catalog graph only —
        # confirmed live this path answered "the data doesn't show a
        # specific value being set" for an attr that WAS genuinely
        # filled this session, because session.filled was never
        # cross-referenced. Only inject values for entities THIS search
        # already found relevant (never the whole filled dict) — a
        # ConfigAttr entity's graph id IS its entity_id, same convention
        # used throughout this file.
        _attrs_by_entity_id = {a.entity_id: a for a in attrs}
        _session_value_lines = []
        for e in entities:
            if not e.type.lower().endswith("bmconfigattr"):
                continue
            _matched_attr = _attrs_by_entity_id.get(e.id)
            if not _matched_attr:
                continue
            _val = session.display_filled.get(_matched_attr.variable_name) \
                or session.filled.get(_matched_attr.variable_name)
            if _val:
                _session_value_lines.append(
                    f"- {_matched_attr.display_label} "
                    f"({_matched_attr.variable_name}): {_val}"
                )
        session_values = "\n".join(_session_value_lines)
        # Phase 3, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md — ask a
        # clarifying question instead of committing to one interpretation,
        # BEFORE synthesising an answer from whatever graph_search
        # returned. Gated on cpq_qa_ambiguity_check_enabled. Reuses the
        # SAME universal classifier as Phase 1/2 — its AMBIGUOUS category
        # + clarifying_question is exactly the "ask before guessing, even
        # a single word" output this was designed to produce; this is
        # simply its first REAL (non-shadow) consumer, scoped to
        # informational Q&A only (never config-mutating).
        _qa_ambiguity_answer = None
        _qa_it = _qa_ot = 0
        if _ask_api_module.get_settings().cpq_qa_ambiguity_check_enabled:
            try:
                # Reuse the SESSION_STATUS_QUERY check's classify call
                # above when it already ran (identical arguments) --
                # never pay for a second, redundant LLM round-trip on
                # the same turn (PR #213 review finding).
                if meta_result is not None:
                    _qa_intent, _qa_it, _qa_ot = meta_result, meta_prompt_tokens, meta_completion_tokens
                else:
                    _qa_intent, _qa_it, _qa_ot = _ask_api_module._llm_classify_intent_universal(
                        req.question, attrs, session, req.workspace_id)
                if (
                    _qa_intent is not None
                    and _qa_intent.category == IntentCategory.AMBIGUOUS
                    and _qa_intent.confidence != Confidence.LOW
                    and _qa_intent.clarifying_question
                ):
                    _qa_ambiguity_answer = _qa_intent.clarifying_question
            except Exception:  # noqa: BLE001 — must never break the Q&A turn
                _ask_api_module.logger.debug("cpq_qa_ambiguity: check failed", exc_info=True)
        if _qa_ambiguity_answer is not None:
            qa_answer = _qa_ambiguity_answer
            # p_in/p_out/p_ms already reflect the real _extract_terms
            # call above -- s_in/s_out here report the classification
            # call's own real usage (2026-07-28), not zero, since a
            # real LLM call drove this answer (the _synthesise call
            # this branch skips is what would have otherwise reported).
            s_in, s_out, s_ms = _qa_it, _qa_ot, 0
        else:
            qa_answer, s_in, s_out, s_ms = _ask_api_module._synthesise(
                req.question, context, history=req.history, workspace_id=req.workspace_id,
                session_values=session_values,
            )
        return qa_answer, (p_in, p_out, p_ms, s_in, s_out, s_ms)
    except Exception as exc:  # noqa: BLE001
        _ask_api_module.logger.warning("cpq_qa synthesis failed: %s", exc)
        return f"Couldn't reach the graph: {exc}", (0, 0, 0, 0, 0, 0)
