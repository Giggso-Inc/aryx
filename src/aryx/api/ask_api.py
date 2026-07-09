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
from aryx.cpq.engine import CpqEngine, DECISION_REQUIRED_KEYS
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



def _persist_cpq_history(workspace_id: int, question: str, answer: str) -> None:
    try:
        hstore = AskHistoryStore(get_settings().rdb_dsn)
        try:
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                     "menial_model": "cpq-engine", "answer_model": "cpq-engine"}
            hstore.append(workspace_id, question, answer, [], [], usage)
        finally:
            hstore.close()
    except Exception:  # noqa: BLE001
        pass


def _handle_cpq_qa(
    req: "AskRequest",
    session: Any,
    attrs: list,
    reader: Any,
    resume_review: bool = False,
) -> dict[str, Any]:
    """STEP 7 — Contextual Q&A: answer a graph question then resume configuration state.

    Pauses the config loop, queries the graph for context, synthesises an LLM
    answer, then appends the current config resume prompt so the user knows where
    they were. The session state is preserved unchanged.
    """
    types = all_types(reader)
    try:
        terms, p_in, p_out, p_ms = _extract_terms(
            req.question, types, req.history, workspace_id=req.workspace_id,
        )
        entities, calls = gather(reader, terms)
        entities = _enrich_with_attributes(entities, req.workspace_id)
        context = render_context(entities)
        qa_answer, s_in, s_out, s_ms = _synthesise(
            req.question, context, history=req.history, workspace_id=req.workspace_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cpq_qa synthesis failed: %s", exc)
        qa_answer = f"Couldn't reach the graph: {exc}"
        p_in = p_out = p_ms = s_in = s_out = s_ms = 0

    # Append a resume prompt so the user knows where to continue
    if resume_review:
        resume = "\n\n---\n\n" + _cpq_engine.build_review_prompt(
            session.product_name, attrs, session.display_filled,
        )
    elif session.pending_variables:
        pending_attr = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if pending_attr:
            resume = (
                "\n\n---\n\n*Resuming your configuration...*\n\n"
                + _cpq_engine.next_question_prompt(pending_attr)
            )
        else:
            resume = ""
    else:
        resume = ""

    answer = qa_answer + resume
    _persist_cpq_history(req.workspace_id, req.question, answer)

    usage = {
        "prompt_tokens": p_in + s_in,
        "completion_tokens": p_out + s_out,
        "latency_ms": p_ms + s_ms,
        "menial_model": "cpq-qa",
        "answer_model": "cpq-qa",
    }
    return {
        "answer": answer,
        "terms": [],
        "tools_called": ["cpq_qa()"],
        "usage": usage,
        "grounding": None,
        "session_data": session.to_dict(),
        "cpq_payload": None,
    }


def _handle_cascade(
    req: "AskRequest",
    session: Any,
    attrs: list,
    changed_attr: Any,
    new_value_hint: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 — Cascade: apply a change, invalidate dependents, re-run rule loop."""
    by_eid = {a.entity_id: a for a in attrs}
    hints = _cpq_engine.extract_hints(req.question)

    # Find dependent attrs to invalidate
    dependent_eids = _cpq_engine.find_cascade_dependents(
        changed_attr, attrs, hiding_rules, rec_rules, con_rules,
    )
    dependent_labels = [
        by_eid[eid].display_label for eid in dependent_eids if eid in by_eid
    ]

    # Strip changed attr + all dependents from filled
    session.filled.pop(changed_attr.variable_name, None)
    session.display_filled.pop(changed_attr.variable_name, None)
    session.filled_source.pop(changed_attr.variable_name, None)
    for eid in dependent_eids:
        a = by_eid.get(eid)
        if a:
            session.filled.pop(a.variable_name, None)
            session.display_filled.pop(a.variable_name, None)
            session.filled_source.pop(a.variable_name, None)

    # Lock in the new value for the changed attr
    result = _cpq_engine.apply_answer(changed_attr, new_value_hint)
    if result:
        session.filled[changed_attr.variable_name] = result[0]
        session.display_filled[changed_attr.variable_name] = result[1]
        session.filled_source[changed_attr.variable_name] = "user"
    else:
        # Could not parse new value — ask for clarification
        opts_prompt = _cpq_engine.next_question_prompt(changed_attr)
        answer = (
            f"I couldn't match that to a valid option for **{changed_attr.display_label}**. "
            f"Please choose one:\n\n{opts_prompt}"
        )
        session.pending_variables = [changed_attr.variable_name] + [
            v for v in session.pending_variables if v != changed_attr.variable_name
        ]
        session.status = "configuring"
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_cascade()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Re-run full rule evaluation loop with updated state
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id)
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi,
    )
    for var, new_val in filled.items():
        old_val = prev_filled_snapshot.get(var)
        if old_val != new_val:
            session.cascade_log.append({
                "var": var, "old": old_val, "new": new_val,
                "rule": "cascade" if var == changed_attr.variable_name else "cascade-dependent",
                "turn": session.turn,
            })
    session.filled = filled
    session.display_filled = display_filled
    session.pending_variables = [a.variable_name for a in pending]
    session.filled_source = {
        k: v for k, v in session.filled_source.items() if k in filled
    }
    session.filled_multi = {
        k: v for k, v in session.filled_multi.items()
        if any(a.variable_name == k for a in visible_attrs)
    }

    # Build cascade notice
    changed_disp = session.display_filled.get(changed_attr.variable_name, new_value_hint)
    cascade_note = f"Updated **{changed_attr.display_label}** → **{changed_disp}**."
    if dependent_labels:
        cascade_note += (
            f" This invalidated: *{', '.join(dependent_labels)}* — re-evaluating."
        )
    for dvar, dvals in dropped_multi.items():
        dattr = next((a for a in attrs if a.variable_name == dvar), None)
        dlabel = dattr.display_label if dattr else dvar
        cascade_note += (
            f" Removed **{', '.join(dvals)}** from **{dlabel}** — "
            f"no longer valid after this change."
        )

    if pending:
        # New conflicts to resolve → FORMAT A (change notice + next question only)
        session.status = "configuring"
        next_attr = pending[0]
        ctx = _cpq_engine.build_context_sentence(
            next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
        )
        q_block = _cpq_engine.next_question_prompt(
            next_attr, ctx, constrained_opts.get(next_attr.entity_id),
        )
        answer = cascade_note + "\n\n" + q_block
    else:
        # All resolved → FORMAT B JSON
        session.status = "awaiting_approval"
        payload = _cpq_engine.build_payload(filled, session.filled_source, session.filled_multi)
        answer = (
            cascade_note + "\n\n"
            f"Configuration complete for **{session.product_name}**.\n\n"
            f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
            f"Say **confirm** to submit, or describe any changes."
        )

    _persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_cascade()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _run_cpq_turn(req: AskRequest, reader: Any) -> dict[str, Any]:
    """Execute one turn of the 8-step CPQ guided-configuration conversation.

    Step 1 — Anchor validation: block until product_family + country present in NL.
    Step 2 — API value mapping: NL hints → item_value via graph options.
    Step 3 — Rule evaluation loop: hiding → recommendation → constraint, until stable.
    Step 4 — Hybrid prompting: context sentence + numbered list of constrained options.
    Step 5 — Lock & loop: apply user answer, re-enter rule evaluation loop.
    Step 6 — Review & dynamic reconfiguration: show review; cascade on changes.
    Step 7 — Contextual Q&A: answer graph questions mid-flow; resume config state.
    Step 8 — JSON payload synthesis: generate BOM only after explicit user approval.

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

    # ── Extract NL hints (Step 1 prerequisite) ────────────────────────────────
    hints = _cpq_engine.extract_hints(req.question)

    # A direct reply to an anchor question we JUST asked (e.g. a bare "United
    # States") won't match extract_hints' preposition-requiring patterns —
    # when we know exactly what we asked for, treat the raw reply as the
    # answer (CPQ_CASCADE_CONVERSATION_PLAN.md D1).
    if session.pending_anchor == "country" and "country" not in hints:
        hints["country"] = req.question.strip()
    if "country" in hints and not session.country:
        session.country = hints["country"]

    # ── STEP 1: Sequential anchor prompting — product first, then country.
    # hwVersion is no longer an anchor (D1); it resolves through the normal
    # rule cascade like any other dependent variable, once product+country
    # are known. ───────────────────────────────────────────────────────────
    if not session.product_name:
        detected = _cpq_engine.detect_product_mention(req.question, hints)
        if not detected and session.pending_anchor == "product":
            detected = req.question.strip()
        if not detected:
            session.pending_anchor = "product"
            answer = (
                "To start the configuration I need the **product family** "
                "(e.g., *APX Next*, *MOTOTRBO*, *SL3500e*). Could you provide that?"
            )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_anchor_validation()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        session.product_name = detected

    if not session.country:
        session.pending_anchor = "country"
        answer = (
            "Thanks — and what's the **destination country** for this "
            "quote? (e.g., *United States*, *Canada*, *Germany*)"
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_anchor_validation()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    session.pending_anchor = ""

    # ── STEP 2: Resolve product name → item_value mapping ────────────────────
    # session.product_name is always set by this point (Step 1 guarantees
    # it) — load_product_config below may still overwrite it with the
    # graph-resolved canonical name once the product is actually loaded.
    product_name = session.product_name

    attrs, resolved_name = _cpq_engine.load_product_config(
        reader, req.workspace_id, product_name,
    )
    if resolved_name:
        session.product_name = resolved_name

    if not attrs:
        return {}  # no CPQ data in graph — fall through to standard Ask

    # ── Load all rule sets (needed for Step 3, 6, 7) ─────────────────────────
    hiding_rules = _cpq_engine.load_hiding_rules(req.workspace_id)
    rec_rules = _cpq_engine.load_recommendation_rules(req.workspace_id)
    con_rules = _cpq_engine.load_constraint_rules(req.workspace_id)

    # ── STEP 6 / 7 / 8 routing: awaiting_approval status ────────────────────
    if session.status == "awaiting_approval":
        # STEP 8: explicit approval → generate BOM payload
        if _cpq_engine.detect_approval(req.question):
            session.status = "approved"
            session.complete = True
            payload = _cpq_engine.build_payload(session.filled, session.filled_source, session.filled_multi)
            answer = (
                f"```json\n{json.dumps(payload, indent=2)}\n```"
            )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": list(hints.values()),
                "tools_called": ["cpq_payload_approved()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": payload,
            }

        # STEP 7: Q&A during review — answer graph question, then show review again
        if _cpq_engine.detect_qa_question(req.question, strict=False):
            return _handle_cpq_qa(req, session, attrs, reader, resume_review=True)

        # STEP 6: change request → cascade
        change_result = _cpq_engine.detect_change_request(req.question, attrs, session.filled)
        if change_result:
            changed_attr, new_value_hint = change_result
            return _handle_cascade(
                req, session, attrs, changed_attr, new_value_hint,
                hiding_rules, rec_rules, con_rules,
            )

        # Could not parse as approval, Q&A, or change — re-show FORMAT B
        payload = _cpq_engine.build_payload(session.filled, session.filled_source, session.filled_multi)
        answer = (
            f"I didn't quite catch that. Here is the current configuration for "
            f"**{session.product_name}**:\n\n"
            f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
            f"Say **confirm** to submit, or describe what to change."
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_review_nudge()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # ── §6: explicit response-mode request detected early — must win over
    # Step 5's answer-locking, same reason the Q&A strict check already runs
    # first: a message like "show me the json so far" doesn't match any
    # menu option and would otherwise be rejected as an invalid answer. ────
    mode_request = _cpq_engine.detect_response_mode_request(req.question)

    # ── Attribute option query: "what values are available for X?" ────────────
    queried_attr = _cpq_engine.detect_attr_query(req.question, attrs)
    if queried_attr:
        options_block = _cpq_engine.next_question_prompt(queried_attr)
        current_val = session.filled.get(queried_attr.variable_name)
        current_note = (
            f"\n\n*Currently set to: **{session.display_filled.get(queried_attr.variable_name, current_val)}***"
            if current_val else ""
        )
        answer = (
            f"Here are the available values for **{queried_attr.display_label}**:"
            f"\n\n{options_block}{current_note}"
            f"\n\nReply with your choice and I'll update the configuration."
        )
        other_pending = [v for v in session.pending_variables if v != queried_attr.variable_name]
        session.pending_variables = [queried_attr.variable_name] + other_pending
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [queried_attr.variable_name],
            "tools_called": [f"cpq_attr_query({queried_attr.variable_name})"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # ── STEP 7: Q&A during active config (strict — only ? or Q&A keywords) ───
    if session.pending_variables and session.turn > 1:
        pending_var_for_qa = session.pending_variables[0]
        pending_attr_for_qa = next(
            (a for a in attrs if a.variable_name == pending_var_for_qa), None,
        )
        if _cpq_engine.detect_qa_question(req.question, pending_attr_for_qa, strict=True):
            return _handle_cpq_qa(req, session, attrs, reader, resume_review=False)

    # ── STEP 5: Lock user's answer from previous turn ────────────────────────
    if session.pending_variables and session.turn > 1 and not mode_request:
        pending_var = session.pending_variables[0]
        pending_attr = next(
            (a for a in attrs if a.variable_name == pending_var), None,
        )
        if pending_attr:
            vn_flat_pv = pending_var.lower().replace("_", "")
            hint_val_for_attr = next(
                (hv for hk, hv in hints.items()
                 if hk.lower().replace("_", "") in vn_flat_pv
                 or vn_flat_pv in hk.lower().replace("_", "")),
                None,
            )
            # Try the user's full utterance first — they may have typed the exact
            # option name (e.g. "APX NEXT (4G LTE+5G)"). Only fall back to the
            # extracted hint if the full question produces no match; hints are
            # coarse (e.g. "LTE") and can mis-match when multiple options share
            # the same keyword.
            result = _cpq_engine.apply_answer(pending_attr, req.question)
            if not result and hint_val_for_attr:
                result = _cpq_engine.apply_answer(pending_attr, hint_val_for_attr)
            if result:
                iv, disp = result
                session.filled[pending_var] = iv
                session.display_filled[pending_var] = disp
                session.filled_source[pending_var] = "user"
                pv_flat = pending_var.lower().replace("_", "")
                matched_fragment = next(
                    (dk for dk in DECISION_REQUIRED_KEYS if dk in pv_flat), None
                )
                if matched_fragment:
                    for sibling in attrs:
                        svn = sibling.variable_name
                        if svn in session.filled or sibling.options:
                            continue
                        if matched_fragment in svn.lower().replace("_", ""):
                            session.filled[svn] = iv
                            session.display_filled[svn] = disp
                            session.filled_source[svn] = "cascade"
            elif pending_attr.options:
                # Answer matched nothing — tell the user and re-show the options
                opts_prompt = _cpq_engine.next_question_prompt(pending_attr)
                answer = (
                    f"I didn't recognise **\"{req.question.strip()}\"** as a valid choice "
                    f"for **{pending_attr.display_label}**. Please pick one:\n\n{opts_prompt}"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_invalid_answer()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }

    # ── STEP 3: Rule evaluation loop (hide → recommend → constrain) ──────────
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id)
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi,
    )
    dropped_note = "".join(
        f" Removed **{', '.join(dvals)}** from **"
        f"{next((a.display_label for a in attrs if a.variable_name == dvar), dvar)}"
        f"** — no longer valid after this change."
        for dvar, dvals in dropped_multi.items()
    )

    session.filled = filled
    session.display_filled = display_filled
    session.pending_variables = [a.variable_name for a in pending]
    session.filled_source = {
        k: v for k, v in session.filled_source.items() if k in filled
    }
    session.filled_multi = {
        k: v for k, v in session.filled_multi.items()
        if any(a.variable_name == k for a in visible_attrs)
    }
    # Cascade delta log (§7): record every value this pass introduced or
    # changed, tagged with its provenance, so later turns can explain "why"
    # from what actually happened rather than re-deriving it from the
    # current rule set alone.
    for var, new_val in filled.items():
        old_val = prev_filled_snapshot.get(var)
        if old_val != new_val:
            session.cascade_log.append({
                "var": var, "old": old_val, "new": new_val,
                "rule": session.filled_source.get(var, ""), "turn": session.turn,
            })

    if not pending:
        # ── STEP 6: FORMAT B — show complete BOM JSON, gate on confirm ────────
        session.status = "awaiting_approval"
        payload = _cpq_engine.build_payload(filled, session.filled_source, session.filled_multi)
        answer = (
            f"{dropped_note.strip()}\n\n" if dropped_note else ""
        ) + (
            f"Configuration complete for **{session.product_name}**.\n\n"
            f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
            f"Say **confirm** to submit, or describe any changes."
        )
    elif session.turn >= _cpq_engine.MAX_TURNS:
        # Turn cap reached with attrs still unresolved. NEVER fabricate a
        # complete BOM here — a payload presented as final must not contain
        # guessed values. Emit an explicitly-incomplete state and keep the
        # guided flow open on the next pending attribute.
        unresolved = [a.display_label for a in pending]
        next_attr = pending[0]
        q_block = _cpq_engine.next_question_prompt(
            next_attr, "", constrained_opts.get(next_attr.entity_id),
        )
        answer = (
            f"⚠️ The configuration for **{session.product_name}** is "
            f"**incomplete** — {len(unresolved)} attribute(s) still need "
            f"your input: *{', '.join(unresolved[:8])}"
            f"{'…' if len(unresolved) > 8 else ''}*.\n\n"
            f"I won't generate a BOM with guessed values. Let's continue:"
            f"\n\n{q_block}"
        )
    else:
        # ── §6: explicit on-request presentation — JSON preview or the full
        # batch of pending questions — otherwise FORMAT A (one question).
        # mode_request was detected early (before Step 5) so an explicit
        # request never gets rejected as an invalid menu answer. ─────────
        if mode_request == "json":
            preview_payload = _cpq_engine.build_payload(
                filled, session.filled_source, session.filled_multi)
            summary = _cpq_engine.render_filled_summary(display_filled, visible_attrs)
            still_need = ", ".join(a.display_label for a in pending)
            answer = (
                (f"{dropped_note.strip()}\n\n" if dropped_note else "")
                + (f"{summary}\n\n" if summary else "")
                + f"Here's the configuration so far — **preview, not final**:\n\n"
                f"```json\n{json.dumps(preview_payload, indent=2)}\n```\n\n"
                f"Still need: {still_need}."
            )
        elif mode_request == "batch":
            blocks = []
            for a in pending:
                ctx = _cpq_engine.build_context_sentence(
                    a, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
                )
                blocks.append(_cpq_engine.next_question_prompt(
                    a, ctx, constrained_opts.get(a.entity_id)))
            answer = (
                (f"{dropped_note.strip()}\n\n" if dropped_note else "")
                + f"Here's everything still needed ({len(pending)} item(s)):\n\n"
                + "\n\n---\n\n".join(blocks)
            )
        else:
            # ── STEP 4: FORMAT A — context sentence + numbered options only ──
            next_attr = pending[0]
            context_sentence = dropped_note + _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            constrained_vals = constrained_opts.get(next_attr.entity_id)
            # FORMAT A: pure options prompt — no background state, no counters
            answer = _cpq_engine.next_question_prompt(
                next_attr, context_sentence, constrained_vals,
            )

    _persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer,
        "terms": list(hints.values()),
        "tools_called": [f"cpq_config_load(product={session.product_name})"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None,
        "session_data": session.to_dict(),
        "cpq_payload": None,  # payload only generated on STEP 8 approval
        "preview": mode_request == "json",
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
