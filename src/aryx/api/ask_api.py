"""Ask API — natural-language questions answered over the knowledge graph.

Flow: extract terms -> deterministic graph retrieval -> synthesise -> verify
grounding. Returns the answer, graph calls, usage, and the grounding record.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aryx import llm_runtime
from aryx.api.ask_overview import build as build_overview
from aryx.ask import build_grounding
from aryx.ask.evidence import RetrievedEntity
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine, _PRODUCT_PATTERNS
from aryx.cpq.state import ConfigAttr, CpqSession
from aryx.graph.retrieve import all_types, gather, render_context
from aryx.ports import GraphReaderPort, ports
from aryx.queries import load
from aryx.store.ask_history_store import AskHistoryStore
from aryx.store.pool import get_pool

_cpq_engine = CpqEngine()

logger = logging.getLogger(__name__)


def _validate_workspace(workspace_id: int) -> None:
    """Raise 422 if workspace_id does not exist — prevents cross-workspace log pollution."""
    with get_pool(get_settings().rdb_dsn).connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM aryx_workspace WHERE id = %s", (workspace_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"workspace {workspace_id} does not exist",
                )


def _reader(workspace_id: int = 1) -> GraphReaderPort:
    return ports().graph_reader(workspace_id)


class Turn(BaseModel):
    role: str
    text: str


class AskRequest(BaseModel):
    question: str
    history: list[Turn] = []
    workspace_id: int = 1
    session_data: dict = {}  # CPQ session state echoed back from prior turn


def _strip_think(text: str) -> str:
    """Drop any <think> chain-of-thought a model inlines into its answer."""
    text = text.rsplit("</think>", 1)[-1] if "</think>" in text else text
    return text.replace("<think>", "").strip()


def _recent(history: list[Turn], limit: int = 4) -> str:
    if not history:
        return ""
    turns = history[-limit:]
    return "\n".join(f"{t.role}: {t.text}" for t in turns)


# Minimum 3 chars ([A-Z][A-Z0-9]{2,}) prevents matching 2-char SQL/HTTP verbs
# (OR, IN, ID, FK, ...).  Stopword set handles common uppercase words that are
# not product codes and would fire spurious entity lookups.
_CAP_PHRASE = re.compile(r'\b[A-Z][A-Z0-9]{2,}(?:\s+[A-Z][A-Z0-9]+)*\b')
_CAP_STOPWORDS: frozenset[str] = frozenset({
    "AND", "NOT", "FOR", "THE", "ARE", "GET", "PUT", "POST", "API",
    "SQL", "URL", "IDS", "FAQ", "LOV", "BOM", "ERP", "CPQ", "CRM",
})


def _extract_terms(question: str, types: list[str], history: list[Turn],
                   workspace_id: int = 1) -> tuple[list[str], int, int, int]:
    context = _recent(history)
    sys = "You are a precise search-term extractor for a knowledge-graph lookup engine."
    user = (
        "Using the recent conversation to resolve pronouns (it, they, this), extract "
        "1-5 specific entity names, codes, identifiers, or domain keywords from the "
        "CURRENT question that will retrieve the most relevant graph entities. "
        "Include multi-word product names, model codes, and requirement identifiers exactly as written. "
        f"Do NOT include generic category words like {', '.join(types)}. "
        'Reply ONLY as JSON {"terms": ["..."]} with no other text.\n'
        f"{('Recent conversation:' + chr(10) + context + chr(10)) if context else ''}"
        f"CURRENT question: {question}"
    )
    start = time.monotonic()
    text, it, ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
    ms = int((time.monotonic() - start) * 1000)
    try:
        s, e = text.find("{"), text.rfind("}")
        terms = json.loads(text[s:e + 1]).get("terms", [])
    except (ValueError, json.JSONDecodeError):
        terms = []
    terms = [t for t in terms if t]

    # Supplement: regex-extract capitalized product codes / model names from the
    # question text.  Small menial models miss multi-word caps phrases like
    # "APX NEXT" or "APX N70" — this ensures they always reach the entity search.
    type_lower = {t.lower() for t in types}
    terms_lower = {t.lower() for t in terms}
    for phrase in _CAP_PHRASE.findall(question):
        if phrase in _CAP_STOPWORDS:
            continue
        if phrase.lower() not in type_lower and phrase.lower() not in terms_lower:
            terms.append(phrase)
            terms_lower.add(phrase.lower())

    return (terms or [question.strip()]), it, ot, ms


def _synthesise(question: str, context: str, overview: str = "",
                history: list[Turn] | None = None,
                workspace_id: int = 1) -> tuple[str, int, int, int]:
    sys = (
        "You are Aryx, a precise knowledge-graph assistant specialised in product "
        "configuration, requirements management, and enterprise data. "
        "Always answer from the GRAPH FACTS provided. "
        "Cite entity names, attribute values, and relationship chains explicitly. "
        "Synthesise across all entities shown when multiple are present. "
        "Be direct and specific — never hedge when facts are in front of you."
    )
    has_context = bool(context.strip())
    facts = context if has_context else "(none — no specific entity matched)"
    conv = _recent(history or [], limit=6)
    conv_block = f"\nCONVERSATION SO FAR:\n{conv}\n" if conv else ""
    user = (
        "Answer the QUESTION using the evidence below.\n\n"
        "Rules:\n"
        "- GRAPH FACTS present → answer specifically, citing entity names, "
        "attribute values, and relationship chains shown.\n"
        "- GRAPH FACTS empty → use the OVERVIEW to describe what IS tracked "
        "and suggest a concrete follow-up question. "
        "Do NOT say 'no matching entities' or 'not stored'.\n"
        "- Do NOT invent facts not shown in GRAPH FACTS.\n"
        "- Use CONVERSATION SO FAR to resolve pronouns and give continuity.\n"
        "- Format: bullet list for multiple items; direct prose for single answers.\n\n"
        f"{overview}{conv_block}\nGRAPH FACTS:\n{facts}\n\nQUESTION: {question}"
    )
    start = time.monotonic()
    text, it, ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
    ms = int((time.monotonic() - start) * 1000)
    return _strip_think(text), it, ot, ms


def _enrich_with_attributes(
    entities: list[RetrievedEntity], workspace_id: int,
) -> list[RetrievedEntity]:
    """Fetch full entity attributes from PostgreSQL and attach to each entity.

    FalkorDB only stores id/type/name; the complete attribute bag lives in the
    relational store. Enriching here gives the synthesise LLM the actual field
    values (descriptions, codes, requirement text, etc.) rather than just names.
    """
    if not entities:
        return entities
    try:
        with get_pool(get_settings().rdb_dsn).connection() as conn:
            with conn.cursor() as cur:
                for ent in entities:
                    cur.execute(load("select_entity_by_id"), (ent.id, workspace_id))
                    row = cur.fetchone()
                    if row:
                        _, _, attributes = row
                        if isinstance(attributes, str):
                            attributes = json.loads(attributes)
                        ent.attributes = attributes or {}
    except Exception:  # noqa: BLE001
        logger.debug("attribute enrichment skipped", exc_info=True)
    return entities


def _run_cpq_turn(req: AskRequest, reader: Any) -> dict[str, Any]:
    """Execute one turn of the CPQ guided-configuration conversation.

    Turn 1  — parse NL, load config attrs, auto-fill, ask first pending question.
    Turn 2+ — apply user's answer to the pending attr, auto-fill remainder,
              ask next pending question. Complete after MAX_TURNS or when done.

    The session_data dict is echoed back in every response so the client
    sends it on the next turn — no server-side session store needed.
    """
    # Restore or initialise session
    session = (
        CpqSession.from_dict(req.session_data)
        if req.session_data.get("mode") == "cpq"
        else CpqSession()
    )
    session.turn += 1

    # ── Load product config attrs (once per session) ──────────────────────────
    hints = _cpq_engine.extract_hints(req.question)

    # Extract product name from NL question using known product patterns
    if not session.product_name:
        q_lower = req.question.lower()
        product_name = next(
            (label for pattern, label in _PRODUCT_PATTERNS if re.search(pattern, q_lower, re.IGNORECASE)),
            next((v for k, v in hints.items() if "product" in k), ""),
        ) or "APX NEXT"
    else:
        product_name = session.product_name

    attrs, resolved_name = _cpq_engine.load_product_config(
        reader, req.workspace_id, product_name,
    )
    if resolved_name:
        session.product_name = resolved_name

    if not attrs:
        # No CPQ config data in graph yet — fall through to standard Ask
        return {}

    # ── Apply user answer if this is a follow-up turn ─────────────────────────
    if session.pending_variables and session.turn > 1:
        # Find the attr we asked about last turn
        pending_var = session.pending_variables[0]
        pending_attr = next(
            (a for a in attrs if a.variable_name == pending_var), None,
        )
        if pending_attr:
            result = _cpq_engine.apply_answer(pending_attr, req.question)
            if result:
                iv, disp = result
                session.filled[pending_var] = iv
                session.display_filled[pending_var] = disp

    # ── Auto-fill all remaining attrs ─────────────────────────────────────────
    filled, display_filled, pending = _cpq_engine.auto_fill(
        attrs, hints, already_filled=session.filled,
    )
    session.filled = filled
    session.display_filled = display_filled
    session.pending_variables = [a.variable_name for a in pending]

    # ── Decide response ───────────────────────────────────────────────────────
    filled_summary = _cpq_engine.render_filled_summary(display_filled)

    if not pending or session.turn >= _cpq_engine.MAX_TURNS:
        # Configuration complete
        session.complete = True
        payload = _cpq_engine.build_payload(filled)
        answer_lines = [
            f"Configuration complete for **{session.product_name}**.",
            "",
            filled_summary,
            "",
            "**CPQ Payload (ready for BOM API):**",
            "```json",
            json.dumps(payload, indent=2),
            "```",
        ]
        answer = "\n".join(answer_lines)
    else:
        # Ask about the first pending attribute
        next_attr = pending[0]
        question_block = _cpq_engine.next_question_prompt(next_attr)
        remaining = len(pending)
        answer_lines = [
            f"Setting up **{session.product_name}** for you.\n",
            filled_summary,
            "",
            f"({remaining} attribute{'s' if remaining != 1 else ''} left — "
            f"turn {session.turn} of {_cpq_engine.MAX_TURNS})\n",
            question_block,
        ]
        answer = "\n".join(answer_lines)

    # Persist usage (0 tokens — no LLM call in CPQ mode)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
             "menial_model": "cpq-engine", "answer_model": "cpq-engine"}
    try:
        hstore = AskHistoryStore(get_settings().rdb_dsn)
        try:
            hstore.append(req.workspace_id, req.question, answer, [], [], usage)
        finally:
            hstore.close()
    except Exception:  # noqa: BLE001
        pass

    return {
        "answer": answer,
        "terms": list(hints.values()),
        "tools_called": [f"cpq_config_load(product={session.product_name})"],
        "usage": usage,
        "grounding": None,
        "session_data": session.to_dict(),
        "cpq_payload": _cpq_engine.build_payload(filled) if session.complete else None,
    }


class LlmConfigRequest(BaseModel):
    provider: str = ""
    menial_model: str = ""
    answer_model: str = ""
    endpoint: str = ""
    api_key: str = ""


def run_ask(req: AskRequest) -> dict[str, Any]:
    """Execute the Aryx Ask pipeline for a request payload.

    CPQ mode: when the question is a configuration/quote request (or the
    session_data carries a live CPQ session), routes to _run_cpq_turn()
    which drives the guided attribute-by-attribute conversation.

    Standard mode: term extraction → graph retrieval → Grok synthesis.
    """
    reader = _reader(req.workspace_id)

    # ── CPQ routing ───────────────────────────────────────────────────────────
    is_cpq = (
        req.session_data.get("mode") == "cpq"  # continuing a CPQ session
        or _cpq_engine.is_cpq_question(req.question)
    )
    if is_cpq:
        result = _run_cpq_turn(req, reader)
        if result:  # non-empty → CPQ engine handled it
            return result
        # empty → no CPQ data in graph yet, fall through to standard Ask

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
    except Exception as exc:  # noqa: BLE001 — surface model/runtime errors to UI
        logger.warning("ask failed: %s", exc)
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
        hstore = AskHistoryStore(get_settings().rdb_dsn)
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


def ask_router() -> APIRouter:
    router = APIRouter()

    @router.post("/ask")
    def ask(req: AskRequest) -> dict:
        _validate_workspace(req.workspace_id)
        return run_ask(req)

    @router.get("/llm/config")
    def get_llm_config() -> dict:
        return llm_runtime.status()

    @router.post("/admin/llm/config")
    def set_llm_config(req: LlmConfigRequest) -> dict:
        llm_runtime.set_config(**req.model_dump())
        return llm_runtime.status()

    return router
