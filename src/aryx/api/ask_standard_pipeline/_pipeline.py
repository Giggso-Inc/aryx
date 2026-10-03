"""The non-CPQ "standard Ask pipeline" orchestrator.

Split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aryx.raven_log import raven_log

from aryx.llm import llm_runtime
from aryx.api.ask_overview import build as build_overview
from aryx.api.ask_request_models import AskRequest
from aryx.api.ask_standard_pipeline._enrichment import _enrich_with_attributes
from aryx.api.ask_standard_pipeline._synthesis import _synthesise
from aryx.api.ask_standard_pipeline._terms import _extract_terms
from aryx.ask import build_grounding
from aryx.config import get_settings
from aryx.graph.retrieve import all_types, gather, render_context
from aryx.store.ask_history_store import AskHistoryStore

logger = logging.getLogger(__name__)


def _standard_ask_pipeline(req: AskRequest, reader: Any) -> dict[str, Any]:
    """Non-CPQ Ask: term extraction → graph retrieval → synthesis."""
    _t0 = time.monotonic()
    types = all_types(reader)
    overview = build_overview(reader, req.workspace_id)
    try:
        terms, p_in, p_out, p_ms = _extract_terms(
            req.question, types, req.history, workspace_id=req.workspace_id)
        entities, calls = gather(reader, terms)
        entities = _enrich_with_attributes(entities, req.workspace_id)
        context = render_context(entities)
        answer, s_in, s_out, s_ms = _synthesise(
            req.question, context, overview,
            history=req.history, workspace_id=req.workspace_id)
        grounding = build_grounding(answer or "", entities)
        raven_log("DEBUG", "P4", "ask.standard.answered terms searched and answer synthesised", context={
            "term_count": len(terms), "type_count": len(types), "graph_hit_count": len(entities),
            "tool_call_count": len(calls), "answer_len": len(answer or ""),
            "empty_answer": not answer, "duration_ms": int((time.monotonic() - _t0) * 1000),
            "road": "standard"})
    except Exception as exc:  # noqa: BLE001 — surface model/runtime errors to UI
        logger.warning("ask failed: %s", exc)
        raven_log(
            "ERROR", "P2", "ask.answer.degraded standard ask returned an error answer",
            error_code="ARYX_ASK_ANSWER_DEGRADED",
            context={"dependency_name": "oci_genai", "operation": "standard_ask_pipeline",
                     "duration_ms": int((time.monotonic() - _t0) * 1000),
                     "result": "error_answer_returned", "error_class": type(exc).__name__,
                     "attempt": 1, "workspace_id": req.workspace_id},
        )
        return {"answer": f"LLM unavailable: {exc}", "terms": [],
                "tools_called": [], "usage": {}, "grounding": None}
    cfg = llm_runtime.status()
    usage = {
        "prompt_tokens": p_in + s_in,
        "completion_tokens": p_out + s_out,
        "latency_ms": p_ms + s_ms,
        "menial_model": cfg["menial_model"],
        "answer_model": cfg["answer_model"],
    }
    try:
        hstore = AskHistoryStore(get_settings().effective_dsn())
        try:
            hstore.append(req.workspace_id, req.question,
                          answer or "", calls, [], usage)
        finally:
            hstore.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask history persist failed: %s", exc)
    return {"answer": answer or "No answer produced.", "terms": terms,
            "tools_called": calls, "usage": usage,
            "grounding": grounding.to_dict()}
