"""Core turn-independent helpers used throughout `ask_api.py` (final
sweep, Phase 11/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): workspace validation, the graph-reader
factory, a crash-proof product-mention probe, mining CPQ context out of
plain-Ask history (Residual Bug A), the shared per-turn LLM usage dict,
and the history-persistence helper nearly every response in this module
calls. Logic unchanged from the original inline definitions. `_reader`
and `_persist_cpq_history` are re-exported from `ask_api.py` unchanged
since at least one test replaces each via `patch.object(api, ...)`.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from aryx import llm_runtime
from aryx.api.ask_request_models import Turn
from aryx.api.ask_standard_pipeline import _user_texts_from_history
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import CpqSession
from aryx.ports import GraphReaderPort, ports
from aryx.queries import load
from aryx.store.ask_history_store import AskHistoryStore
from aryx.store.pool import get_pool


_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
# Segments _cpq_summary_text asks the LLM to separate its reply by — one
# lead-in sentence + one narration segment per category, code-assembled
# with the real "• Category" headers afterwards (see _cpq_summary_text).
# Distinctive enough that real narration text won't produce it by accident.
_CPQ_SEGMENT_DELIM = "@@@"


def _validate_workspace(workspace_id: int) -> None:
    """Raise 422 if workspace_id does not exist — prevents cross-workspace log pollution."""
    with get_pool(get_settings().effective_dsn()).connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("select_workspace_by_id"), (workspace_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"workspace {workspace_id} does not exist",
                )


def _reader(workspace_id: int = 1) -> GraphReaderPort:
    return ports().graph_reader(workspace_id)


def _safe_detect_product_mention(question: str, reader: Any, workspace_id: int) -> str:
    """`CpqEngine.detect_product_mention`, but never lets a lookup failure
    (e.g. a test-double `reader` without the real graph methods) propagate
    into a gate that has no business crashing a turn — degrades to "no
    mention found," the same never-guess convention every other
    best-effort gate in this file already uses."""
    from aryx.api import ask_api as _ask_api_module
    try:
        return _ask_api_module._cpq_engine.detect_product_mention(question, {}, reader, workspace_id)
    except Exception as exc:  # noqa: BLE001
        _ask_api_module.logger.debug("cpq quantity gate: detect_product_mention failed: %r", exc)
        return ""


def _mine_history_for_cpq_context(
    session: CpqSession,
    history: list[Turn],
    engine: Any,
) -> None:
    """Recover country / order utterance when turn 1 was standard Ask (not CPQ).

    Residual Bug A: latch logic only runs inside ``_run_cpq_turn``. If the
    first order sentence was answered by the graph pipeline, no CpqSession
    existed — country and the long order text were never stashed. When CPQ
    finally starts (e.g. user says "need to get the quote" / family code),
    mine the last few history user-turns via extract_hints so country-once
    and product_anchor still work.
    """
    from aryx.api import ask_api as _ask_api_module
    texts = _user_texts_from_history(history)
    if not texts:
        return

    from aryx.cpq.intent_gateway import soft_quote_heuristic

    order_candidates = [
        t for t in texts
        if soft_quote_heuristic(t) or engine.extract_hints(t).get("country")
    ]
    if order_candidates:
        best = max(order_candidates, key=len)
        prior = session.product_anchor_question or ""
        if not prior or len(best) > len(prior):
            session.product_anchor_question = best
            _ask_api_module.logger.info(
                "cpq: mined product_anchor_question from history (%d chars)",
                len(best),
            )

    if session.country:
        return

    for text in reversed(texts):
        country = engine.extract_hints(text).get("country")
        canonical_country = country and engine.is_recognized_country(country)
        if canonical_country:
            session.country = canonical_country
            _ask_api_module.logger.info(
                "cpq: mined country=%r from Ask history (pre-CPQ turn)",
                canonical_country,
            )
            return


def _current_turn_usage_dict(default_model: str = "cpq-engine") -> dict[str, Any]:
    """Real per-turn LLM usage accumulated so far, or the deterministic default.

    docs/CPQ_Usage_Reporting_Gap — same llm_runtime.get_turn_usage() ContextVar
    _apply_real_llm_usage reads from; shared here so every one of the ~50
    _persist_cpq_history call sites scattered through _run_cpq_turn_inner
    picks up real tokens/model too, without touching each one individually.
    """
    real = llm_runtime.get_turn_usage()
    if real and real["calls"]:
        models = ", ".join(real["models"]) or default_model
        return {
            "prompt_tokens": real["prompt_tokens"],
            "completion_tokens": real["completion_tokens"],
            "latency_ms": real["latency_ms"],
            "menial_model": models,
            "answer_model": models,
        }
    return {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": default_model, "answer_model": default_model}


def _persist_cpq_history(workspace_id: int, question: str, answer: str) -> None:
    try:
        hstore = AskHistoryStore(get_settings().effective_dsn())
        try:
            usage = _current_turn_usage_dict()
            hstore.append(workspace_id, question, answer, [], [], usage)
        finally:
            hstore.close()
    except Exception:  # noqa: BLE001
        pass
