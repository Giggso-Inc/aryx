"""Ask API — natural-language questions answered over the knowledge graph.

Flow: extract terms -> deterministic graph retrieval -> synthesise -> verify
grounding. Returns the answer, graph calls, usage, and the grounding record.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aryx import llm_runtime
from aryx.api.ask_overview import build as build_overview
from aryx.ask import build_grounding
from aryx.ask.evidence import RetrievedEntity
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine, DECISION_REQUIRED_KEYS
from aryx.cpq.logging_context import install_run_id_logging, set_run_id
from aryx.cpq.state import ConfigAttr, CpqSession
from aryx.graph.retrieve import all_types, gather, render_context
from aryx.ports import GraphReaderPort, ports
from aryx.queries import load
from aryx.store.ask_history_store import AskHistoryStore
from aryx.store.pool import get_pool

_cpq_engine = CpqEngine()

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


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


_MAX_ANSWER_LINES = 5
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _line_count(text: str) -> int:
    """Logical line count — the greater of physical newlines and sentence count.

    A model asked for "N lines" can still return one dense multi-sentence
    paragraph with no line breaks at all; counting sentences too catches that.
    """
    physical = len([ln for ln in text.splitlines() if ln.strip()])
    sentences = len([s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()])
    return max(physical, sentences)


def _rewrite_plain(text: str, context_hint: str, workspace_id: int) -> tuple[str, int, int]:
    """Force a short, plain-English rewrite. Returns the original untouched on any failure.

    Shared by `_enforce_plain_answer` (Q&A) and `_cpq_summary_text` (config
    summaries) — the flow must never block on the rewrite.
    """
    sys = "You rewrite text in plain, everyday English for a non-technical reader."
    user = (
        f"Rewrite the TEXT below to at most {_MAX_ANSWER_LINES} short lines, one "
        "idea per line, in plain jargon-free English — direct point first. Keep "
        "every fact and proper noun (product names, codes) exactly as given; "
        "don't invent or drop any.\n\n"
        f"{context_hint}\n\nTEXT:\n{text}"
    )
    try:
        rewritten, it, ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        rewritten = _strip_think(rewritten).strip()
        if rewritten:
            return rewritten, it, ot
    except Exception:  # noqa: BLE001
        logger.debug("plain-language rewrite failed — using original", exc_info=True)
    return text, 0, 0


def _enforce_plain_answer(
    text: str, question: str, workspace_id: int,
) -> tuple[str, int, int, int]:
    """Second pass: force a short, plain-English rewrite if the model overran."""
    if _line_count(text) <= _MAX_ANSWER_LINES:
        return text, 0, 0, 0
    start = time.monotonic()
    rewritten, it, ot = _rewrite_plain(text, f"QUESTION: {question}", workspace_id)
    ms = int((time.monotonic() - start) * 1000) if (it or ot) else 0
    return rewritten, it, ot, ms


def _synthesise(question: str, context: str, overview: str = "",
                history: list[Turn] | None = None,
                workspace_id: int = 1) -> tuple[str, int, int, int]:
    sys = (
        "You are Aryx, a knowledge-graph assistant. You explain product "
        "configuration, requirements, and enterprise data in plain, everyday "
        "English — the way you'd explain it to a colleague who isn't technical. "
        "Always answer from the GRAPH FACTS provided. "
        "Name the specific things you're talking about (products, values, "
        "relationships) but describe them in plain words, never technical or "
        "internal terminology. Be direct and specific — never hedge when facts "
        "are in front of you."
    )
    has_context = bool(context.strip())
    facts = context if has_context else "(none — no specific entity matched)"
    conv = _recent(history or [], limit=6)
    conv_block = f"\nCONVERSATION SO FAR:\n{conv}\n" if conv else ""
    user = (
        "Answer the QUESTION using the evidence below.\n\n"
        "Rules:\n"
        "- GRAPH FACTS present → answer specifically, naming the entities, "
        "values, and relationships shown, in plain language.\n"
        "- GRAPH FACTS empty → use the OVERVIEW to describe what IS tracked "
        "and suggest a concrete follow-up question. "
        "Do NOT say 'no matching entities' or 'not stored'.\n"
        "- Do NOT invent facts not shown in GRAPH FACTS.\n"
        "- Use CONVERSATION SO FAR to resolve pronouns and give continuity.\n"
        f"- Format: maximum {_MAX_ANSWER_LINES} lines. Lead with a direct "
        "one-line answer, then supporting detail in the order a person would "
        "naturally explain it. Use a short list only when multiple distinct "
        "items are being enumerated. Plain, everyday English — no technical "
        "or internal terms.\n\n"
        f"{overview}{conv_block}\nGRAPH FACTS:\n{facts}\n\nQUESTION: {question}"
    )
    start = time.monotonic()
    text, it, ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
    ms = int((time.monotonic() - start) * 1000)
    text = _strip_think(text)
    text, r_it, r_ot, r_ms = _enforce_plain_answer(text, question, workspace_id)
    return text, it + r_it, ot + r_ot, ms + r_ms


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


def _cpq_summary_text(
    display_filled: dict[str, str],
    attrs: list[ConfigAttr],
    rule_governed_ids: set[int],
    product_name: str,
    workspace_id: int,
) -> str:
    """Structured, headed/bulleted summary of the filtered configuration.

    The engine's `categorized_summary_groups` owns ALL filtering (booleans,
    secondary/warranty/product attrs, year durations, rule-governed set,
    "(none)" placeholders) AND the same 4-category grouping (Product Name /
    Service Plan / Quantity & Duration / Associated Options) the
    deterministic fallback (`render_filled_summary`) uses. The model is
    instructed to reproduce that SAME headed/bulleted shape in its own
    wording (plain-English labels, not raw variable names) rather than
    free prose — earlier revisions asked for flowing paragraphs instead,
    which never actually matched the "scannable, headed" format this was
    built for. `_MAX_ANSWER_LINES`'s generic line cap and its header-blind
    `_rewrite_plain` rewrite pass are deliberately NOT applied here — both
    are tuned for short prose answers and would flatten the headers/bullets
    this prompt now asks for. Any LLM failure or empty reply falls back to
    `render_filled_summary` — the CPQ flow must never block on the
    narrator.
    """
    groups = _cpq_engine.categorized_summary_groups(
        display_filled, attrs, rule_governed_ids=rule_governed_ids)
    if not groups:
        return ""
    sys = (
        "You summarise product configurations for sales reps in plain, "
        "everyday English — never technical or internal terminology."
    )
    config_text = "\n\n".join(
        f"{category}:\n"
        + "\n".join(f"- {label}: {value}" for label, value in pairs)
        for category, pairs in groups
    )
    user = (
        f"Summarise this {product_name or 'product'} configuration for a "
        "sales rep. Lead with one direct line (e.g. 'Your configuration is "
        "complete.'). Then reproduce the EXACT structure below: for each "
        "category, print a bold header line '**Category Name:**' (using "
        "the category names exactly as given, in the same order — never "
        "merge, reorder, or invent one), followed by its facts as short "
        "markdown bullets '- **Label** → value', one bullet per fact, "
        "using plain-English labels instead of raw variable names. "
        "EXCEPTION: for the 'Associated Options' category only, skip bullets "
        "entirely and instead write ONE short plain-text line under its "
        "header — you do not need to mention every fact in that category; "
        "pick whichever subset you can state with total accuracy and "
        "simply OMIT the rest. Never paraphrase, generalise, or invent a "
        "placeholder for a fact you are dropping (e.g. never write "
        "anything like 'plus the usual defaults') — an omitted fact must "
        "be invisible, not gestured at. Use ONLY the exact facts below; if "
        "you are not certain a name or value is precisely what you are "
        "about to write, leave it out rather than guess or approximate "
        "it.\n\nCONFIGURATION:\n" + config_text
    )
    try:
        # ARYX_LLM_REASON_MODEL (role="answer"), not menial — this narration
        # is the customer-facing summary of a real quote; the same reasoning
        # tier already used for CPQ's own BML Tier-2 script fallback.
        text, _it, _ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
        text = _strip_think(text).strip()
        if text:
            return text
    except Exception:  # noqa: BLE001
        logger.debug("cpq: summary narration failed — using bullet fallback",
                     exc_info=True)
    return _cpq_engine.render_filled_summary(
        display_filled, attrs, rule_governed_ids=rule_governed_ids)


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
    # Fast path: question asks about a specific attribute's available options.
    # Uses attr.options already in memory from BmMenuItem — no graph query,
    # no LLM synthesis, no schema leakage possible.
    _attr_q = _cpq_engine.detect_attr_query(req.question, attrs)
    _presentable = (
        [o for o in _attr_q.options if o.display_name.strip()]
        if _attr_q else []
    )
    if _presentable:
        _numbered = "\n".join(
            f"{i + 1}. {o.display_name}" for i, o in enumerate(_presentable)
        )
        qa_answer = (
            f"The available options for **{_attr_q.display_label}** are:\n\n{_numbered}"
        )
        p_in = p_out = p_ms = s_in = s_out = s_ms = 0
    else:
        types = all_types(reader)
        try:
            terms, p_in, p_out, p_ms = _extract_terms(
                req.question, types, req.history, workspace_id=req.workspace_id,
            )
            entities, calls = gather(reader, terms)
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
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    # Accumulate across turns (not just this one) — see CpqSession.negated_vns.
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

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
    if changed_attr.select_type == "multi":
        # UNION every mentioned option with the current selection — a
        # post-completion "include Locking Molle Mount" ADDS a row, it
        # doesn't wipe rows already chosen (and a previously DECLINED
        # empty grid simply becomes the new rows). apply_multi_answer
        # extracts all named options, not just the best single match.
        mentioned = _cpq_engine.apply_multi_answer(changed_attr, new_value_hint)
        result = ("", "") if not mentioned else mentioned[0]
        if mentioned:
            existing = session.filled_multi.get(changed_attr.variable_name, [])
            merged = list(existing) + [iv for iv, _dn in mentioned if iv not in existing]
            session.filled_multi[changed_attr.variable_name] = merged
            session.display_filled[changed_attr.variable_name] = ", ".join(
                next((o.display_name for o in changed_attr.options if o.item_value == v), v)
                for v in merged
            )
            session.filled_source[changed_attr.variable_name] = "user"
        else:
            result = None
    else:
        result = _cpq_engine.apply_answer(changed_attr, new_value_hint)
        if result:
            session.filled[changed_attr.variable_name] = result[0]
            session.display_filled[changed_attr.variable_name] = result[1]
            session.filled_source[changed_attr.variable_name] = "user"
    if not result:
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
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask,
    )
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)
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
        k: v for k, v in session.filled_source.items()
        if k in filled or k in session.filled_multi
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
        # All resolved → verbose summary, JSON only on request (§6/Phase K)
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id,
        )
        answer = (
            cascade_note + "\n\n"
            f"Configuration complete for **{session.product_name}**.\n\n"
            + (f"{summary}\n\n" if summary else "")
            + f"Click **JSON** below to see the full payload, "
              f"say **confirm** to submit, or describe any changes."
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
    if not session.run_id:
        # Minted once per session (fresh session, or an existing one that
        # predates this field) and stable for every subsequent turn since
        # it's echoed back in session_data like every other CpqSession
        # field — traces this quote's whole lifecycle across turns, not
        # just this one request.
        session.run_id = uuid.uuid4().hex
    set_run_id(session.run_id)
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
    elif (session.country and "country" not in hints
          and session.pending_anchor != "switch_country"):
        # A country confirmed on an EARLIER turn must keep filling
        # country-shaped attrs on every later turn, exactly as the original
        # hint did on the turn it arrived. Without this, a product switch
        # that PRESERVED a validated country (Issue 5's re-validation) still
        # re-asked Ultimate Destination Country — the switch-turn message
        # ("videoSolutions_BOM") carries no country hint, so the new
        # catalog's country attr pended despite session.country being both
        # set and confirmed available for the new product (Issue 9 follow-up,
        # found live the moment Bill Country stopped masking it).
        # `!= "switch_country"`: that gate is WAITING for a replacement
        # country — injecting the old (already-invalid) one here would
        # shadow the user's actual reply ("Canada" → hints["country"] =
        # "United States"), caught immediately by
        # test_switch_completes_once_a_valid_new_country_is_given.
        hints["country"] = session.country

    # ── Mid-session product-switch gate ───────────────────────────────────────
    # A PRIOR turn detected a different product than session.product_name and
    # asked the user to confirm before discarding the in-progress config. THIS
    # turn's raw reply is that yes/no answer, not a new CPQ hint (Andie-planned
    # fix for: "CPQ for two products is not working in the single session").
    def _complete_product_switch(new_product: str, new_country: str) -> None:
        """Reset config-scoped state and commit the switch. `new_country`
        is carried over as-is (already validated by the caller, or simply
        never set) — never blindly cleared, so a client who already gave a
        valid country for the new product doesn't have to repeat it."""
        session.cascade_log.append({
            "event": "product_switch", "from": session.product_name,
            "to": new_product, "turn": session.turn,
        })
        session.filled = {}
        session.filled_multi = {}
        session.display_filled = {}
        session.filled_source = {}
        session.pending_variables = []
        session.status = "configuring"
        session.country = new_country
        # NOTE: catalog_prefix is not a CpqSession field — it's derived
        # fresh from attrs[0].catalog_prefix every turn in Step 2 below,
        # so there's nothing session-scoped to reset here.
        session.product_entity_id = 0
        session.negated_vns = []
        session.product_name = new_product
        session.pending_switch_product = ""
        session.pending_switch_candidates = []
        session.pending_anchor = ""
        logger.info(
            "cpq_switch: switched turn=%s new_product=%r country=%r — config state reset",
            session.turn, new_product, new_country or "(none — will be asked fresh)",
        )

    def _country_available_for(product_name: str, country_value: str) -> bool:
        """Best-effort: is country_value compatible with product_name's own
        constraint rules? See CpqEngine.check_country_availability's
        docstring — reuses the same rule-evaluation machinery as every
        other constraint in this engine (declarative AND BML-script-backed
        alike) rather than a hand-rolled lookup. Fails open (True) if the
        new catalog can't be loaded at all — never blocks a switch on an
        inability to check, only on a confirmed real restriction.

        country_value is session.country — DISPLAY text ("United States"),
        not a canonical item_value ("US"), and the new catalog's constraint
        scripts may also read fields DERIVED from the country (region,
        customer type) that a bare one-key dict never contains. So instead
        of seeding check_country_availability with raw text (review finding
        P1: constraints never fired, the check always passed), run the SAME
        cascade a real first turn on the new catalog runs —
        evaluate_rules_loop canonicalizes the country hint to its
        item_value via auto_fill and populates the derived fields via
        recommendation rules — and evaluate availability against that
        resulting filled state. Only runs on a switch turn, never on
        ordinary answers.
        """
        new_attrs, _resolved = _cpq_engine.load_product_config(reader, req.workspace_id, product_name)
        if not new_attrs:
            return True
        new_prefix = new_attrs[0].catalog_prefix
        country_attr = next(
            (a for a in new_attrs if _cpq_engine._is_country_anchor_var(a.variable_name)), None,
        )
        if country_attr is None:
            return True
        new_hiding = _cpq_engine.load_hiding_rules(req.workspace_id, new_prefix)
        new_rec_rules, new_con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
            req.workspace_id, new_prefix)
        new_bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, new_prefix)
        # evaluate_rules_loop returns the resulting filled dict (auto_fill
        # copies rather than mutating the one passed in) — capture it.
        _vis, sim_filled, _disp, _copts = _cpq_engine.evaluate_rules_loop(
            new_attrs, {"country": country_value}, {},
            new_hiding, new_rec_rules, new_con_rules,
            bml_eval=new_bml_eval, country=country_value,
        )
        return _cpq_engine.check_country_availability(
            new_attrs, new_con_rules, sim_filled, new_bml_eval,
        )

    if session.pending_anchor == "switch_country":
        # A prior turn found the carried-over country invalid for the new
        # product and asked for a different one — this turn's text is that
        # attempt (same "bare reply" convention as the normal country
        # anchor: try the NL-hint extractor first, else the raw trimmed
        # text — CPQ_CASCADE_CONVERSATION_PLAN.md D1).
        #
        # Decline path first (Issue 10, docs/CPQ_PRODUCT_SWITCH_ISSUE.md):
        # this state previously had NO way out — every reply was treated
        # as a country attempt, and worse, a decline-shaped reply ("no")
        # could silently COMPLETE the switch with a garbage country, since
        # an unmatchable country fills nothing, no constraint fires, and
        # the availability check fails open by design. EXACT-phrase match
        # only — confirm_switch's startswith(("n","no")) convention would
        # swallow real countries here (Norway, Netherlands, Nigeria,
        # North Macedonia all start with "n").
        _sc_reply = req.question.strip().lower()
        if _sc_reply in ("n", "no", "cancel", "stop", "abort",
                         "never mind", "nevermind"):
            session.pending_switch_product = ""
            session.pending_anchor = ""
            logger.info(
                "cpq_switch: switch_country declined turn=%s staying on product=%r",
                session.turn, session.product_name,
            )
            answer = f"OK — continuing with **{session.product_name}**."
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        new_country = hints.get("country") or req.question.strip()
        new_product = session.pending_switch_product
        if _country_available_for(new_product, new_country):
            _complete_product_switch(new_product, new_country)
            # Fall through — Step 1 below sees session.country already set
            # and session.product_name already the new product, so it
            # proceeds straight to Step 2 for the new catalog.
        else:
            logger.info(
                "cpq_switch: country=%r still invalid for pending_product=%r turn=%s",
                new_country, new_product, session.turn,
            )
            answer = (
                f"**{new_product}** isn't available for **{new_country}** either. "
                f"Could you provide a different country to continue switching?"
            )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_country_invalid()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
    elif session.pending_anchor == "suggest_switch":
        # A prior turn offered SEVERAL "did you mean...?" families (see the
        # suggestion block below) — a bare "yes" can't pick one of 2+, so
        # re-prompt with the list instead of guessing. A "no" (or any other
        # text) clears the state and falls through to normal handling —
        # a reply naming one of the candidates is then caught by regular
        # switch detection later this same turn, which routes it into the
        # standard confirm_switch flow.
        _sreply = req.question.strip().lower()
        if _sreply.startswith(("y", "yes")):
            cand_list = ", ".join(f"**{c}**" for c in session.pending_switch_candidates)
            answer = (
                f"Which one did you mean: {cand_list}? Reply with the "
                f"product name — or say **no** to continue with "
                f"**{session.product_name}**."
            )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_ambiguous()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        session.pending_anchor = ""
        session.pending_switch_candidates = []
        if _sreply.startswith(("n", "no")):
            answer = f"OK — continuing with **{session.product_name}**."
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        # Anything else falls through — normal turn handling (including
        # switch detection on a candidate name) takes over.
    elif session.pending_anchor == "confirm_switch":
        reply = req.question.strip().lower()
        # Affirmative includes replying with the offered product's own name
        # ("videoSolutions_BOM" to "switch to videoSolutions_BOM?") — a
        # natural way to accept that previously counted as a decline.
        _pending_norm = re.sub(r"[^a-z0-9]", "", session.pending_switch_product.lower())
        affirmative = (
            reply.startswith(("y", "yes", "switch", "confirm"))
            or (_pending_norm and re.sub(r"[^a-z0-9]", "", reply) == _pending_norm)
        )
        logger.info(
            "cpq_switch: confirm-reply turn=%s current=%r pending=%r reply=%r decision=%s",
            session.turn, session.product_name, session.pending_switch_product,
            req.question, "switch" if affirmative else "stay",
        )
        if affirmative:
            new_product = session.pending_switch_product
            old_country = session.country
            if old_country and not _country_available_for(new_product, old_country):
                session.pending_anchor = "switch_country"
                logger.info(
                    "cpq_switch: country=%r invalid for new_product=%r turn=%s — "
                    "asking for a different country before completing the switch",
                    old_country, new_product, session.turn,
                )
                answer = (
                    f"**{new_product}** isn't available for **{old_country}**. "
                    f"Could you provide a different country to continue switching?"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_switch_country_invalid()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            _complete_product_switch(new_product, old_country)
            # Fall through — Step 1's anchor block below re-anchors the
            # country for the new product only if it's still empty (a
            # validated carried-over country is preserved, never re-asked).
        else:
            session.pending_switch_product = ""
            session.pending_anchor = ""
            logger.info(
                "cpq_switch: declined turn=%s staying on product=%r",
                session.turn, session.product_name,
            )
            answer = f"OK — continuing with **{session.product_name}**."
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }

    # ── STEP 1: Sequential anchor prompting — product first, then country.
    # hwVersion is no longer an anchor (D1); it resolves through the normal
    # rule cascade like any other dependent variable, once product+country
    # are known. ───────────────────────────────────────────────────────────
    # Whether the product was anchored BEFORE this turn — switch detection
    # (now after Step 2, see Issue 6 in docs/CPQ_PRODUCT_SWITCH_ISSUE.md)
    # must only run for messages sent to an already-anchored session, never
    # on the very message that anchored it.
    product_was_anchored = bool(session.product_name)
    if not session.product_name:
        detected = _cpq_engine.detect_product_mention(req.question, hints, reader, req.workspace_id)
        if not detected and session.pending_anchor == "product":
            detected = req.question.strip()
        if not detected:
            # Priority 2: resolve against real ingested catalog/family/
            # product-option data instead of falling back to accepting
            # raw text unconditionally. Confirmed live this closes two
            # real gaps at once: (a) products outside the fixed pattern
            # list, e.g. "DGM 8500e", now resolve correctly with zero
            # hardcoded entries; (b) a reply to the "what family?" question
            # below is now validated the SAME way instead of being accepted
            # verbatim — previously a bare "US" (a country, not a family)
            # silently became session.product_name = "US", which then
            # resolved to an unrelated phantom "APX6500" quote nobody asked
            # for. Runs on every turn product_name is still unset, so it
            # equally validates the very first message and any retry.
            match = _cpq_engine.resolve_product_hint(reader, req.workspace_id, req.question)
            if match:
                detected = match[1]
        if not detected:
            already_asked = session.pending_anchor == "product"
            session.pending_anchor = "product"
            families = _cpq_engine.list_ingested_families(reader, req.workspace_id)
            fam_list = ", ".join(f"*{f}*" for f in families) if families else "*APX Next*, *MOTOTRBO*, *SL3500e*"
            if already_asked:
                answer = (
                    f"I still couldn't match **{req.question.strip()}** to a "
                    f"product family ingested in this workspace. Available "
                    f"families: {fam_list}. Could you pick one of those?"
                )
            else:
                answer = (
                    f"To start the configuration I need the **product family** "
                    f"(e.g., {fam_list}). Could you provide that?"
                )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_anchor_validation()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        session.product_name = detected
        logger.info("cpq_switch: product anchored turn=%s product=%r", session.turn, detected)

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

    # A product-switch (or the initial turn's own NL detection) already
    # PROVED session.product_name against this catalog — asking the
    # productSelectionProduct_all question again on the very next turn
    # would ignore that proof and re-derive it from a reply ("yes") that
    # carries no product hint at all. Seed it directly from the resolved
    # name via the same fuzzy option-matcher normal answers use, mirroring
    # the confirmed-country carry-over above. Guarded on "not yet filled"
    # so this only fires once (turn 1, or the turn right after
    # _complete_product_switch reset session.filled) and never clobbers a
    # value a later turn's real answer already set.
    if "productSelectionProduct_all" not in session.filled:
        _product_attr = next(
            (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
        )
        if _product_attr is not None:
            _match = _cpq_engine.apply_answer(_product_attr, session.product_name)
            if _match:
                _item_value, _display_name = _match
                session.filled["productSelectionProduct_all"] = _item_value
                session.display_filled["productSelectionProduct_all"] = _display_name
                session.filled_source["productSelectionProduct_all"] = "product_anchor"
                logger.info(
                    "cpq: seeded productSelectionProduct_all=%r from resolved "
                    "product_name=%r turn=%s — skips a redundant re-ask",
                    _item_value, session.product_name, session.turn,
                )

    if product_was_anchored:
        # Product already anchored on an earlier turn — re-check THIS turn's
        # text for a mention of a DIFFERENT product. detect_product_mention
        # is dynamic (matches against whatever catalogs are actually
        # ingested in this workspace, not a hardcoded list) and fuzzy —
        # the confirm gate below is the safety net regardless.
        #
        # ANSWER-OVER-SWITCH PRECEDENCE (Issue 6,
        # docs/CPQ_PRODUCT_SWITCH_ISSUE.md): a message that validly answers
        # the currently-pending attribute is an ANSWER, never a switch
        # signal — confirmed live: answering the pending Product menu with
        # "APX 6500" scored 0.67 against the alias "APX™ N70" and was
        # hijacked into a "did you mean aSTRO25_bom?" prompt instead of
        # locking. This check needs the pending attr's OPTIONS, which is
        # why detection now runs after Step 2 loads attrs (the same
        # structural constraint that killed the pre-Step-2 word-count gate
        # in an earlier design round). Options-backed matches only — the
        # free-text tier of apply_answer is deliberately not consulted,
        # since it would classify ANY text as an answer while a free-text
        # attr is pending, swallowing every switch mention.
        pending_attr_guard = next(
            (a for a in attrs
             if session.pending_variables
             and a.variable_name == session.pending_variables[0]),
            None,
        )
        is_answer_to_pending = bool(
            pending_attr_guard is not None
            and pending_attr_guard.options
            and _cpq_engine.apply_answer(pending_attr_guard, req.question)
        )
        # productSelectionProduct_all's option list is shared, catalog-wide
        # (the exact same ~325 SKU codes on every ingested catalog — see
        # engine.py's own docstrings on this attr) — confirmed live: a
        # genuine switch sentence ("Quote APX Next Enhanced radios...")
        # legitimately option-matched against THIS unrelated catalog's copy
        # of that same list (APX NEXT ENHANCED really is one of its 325
        # options too), so is_answer_to_pending was True and the switch
        # mention never got checked at all — the wrong product's code
        # silently landed in the wrong catalog's build. For this one
        # attr specifically, always check switch-detection FIRST and only
        # trust the option-match if no other ingested product was named —
        # every other pending attr's option list is catalog-specific, so
        # the original answer-over-switch precedence (Issue 6 above) stays
        # unchanged for them, preserving the "APX 6500" fix it exists for.
        # An exact, standalone match against one of THIS attr's own options
        # (the whole reply, not a substring within a longer sentence) is a
        # strong "definitely answering" signal regardless of what else the
        # text might also resemble — confirmed live: "APX NEXT Single Band"
        # is a real SL3500e-catalog option whose own text happens to
        # contain a different family's alias ("APX NEXT"), and must still
        # lock as an answer. Only a longer sentence that merely CONTAINS an
        # option string (e.g. "Quote APX Next Enhanced radios for a US
        # customer.") is ambiguous enough to need the switch-mention probe
        # below.
        _reply_norm = req.question.strip().lower()
        is_exact_option_reply = bool(
            pending_attr_guard is not None
            and any(
                _reply_norm in (o.item_value.strip().lower(), o.display_name.strip().lower())
                for o in (pending_attr_guard.options or ())
            )
        )
        alias_map: dict[str, str] | None = None
        switch_candidate: str | None = None
        if (
            is_answer_to_pending
            and not is_exact_option_reply
            and pending_attr_guard is not None
            and pending_attr_guard.variable_name == "productSelectionProduct_all"
        ):
            alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
            switch_candidate = _cpq_engine.detect_product_mention(
                req.question, hints, reader, req.workspace_id,
                alias_map=alias_map,
            )
            if (
                switch_candidate
                and switch_candidate.strip().lower() != session.product_name.strip().lower()
            ):
                is_answer_to_pending = False
        if not is_answer_to_pending:
            # Alias inventory fetched ONCE for this turn, and only on the
            # non-answer path (review finding P2 — plus the answer guard
            # above now skips the fetch entirely for ordinary answers).
            # Reuse the probe above when the productSelectionProduct_all
            # guard already computed it — no need to hit the graph twice.
            if alias_map is None:
                alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
                switch_candidate = _cpq_engine.detect_product_mention(
                    req.question, hints, reader, req.workspace_id,
                    alias_map=alias_map,
                )
            if switch_candidate and switch_candidate.strip().lower() != session.product_name.strip().lower():
                logger.info(
                    "cpq_switch: candidate detected turn=%s current=%r candidate=%r",
                    session.turn, session.product_name, switch_candidate,
                )
                session.pending_switch_product = switch_candidate
                session.pending_anchor = "confirm_switch"
                answer = (
                    f"It looks like you're asking about **{switch_candidate}**, but this "
                    f"session is configuring **{session.product_name}**. Switch to "
                    f"**{switch_candidate}** and discard the current configuration? (yes/no)"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_switch_candidate()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }

            # No confident switch candidate — but the message might still be
            # a garbled/partial attempt at naming a product (fuzzy score in
            # the "maybe" band, below confirm-worthy but above pure noise).
            # Rather than silently ignore it, offer up to 5 real candidates
            # so the client isn't left unrecognised with no signal anything
            # was ambiguous.
            suggestions = _cpq_engine.suggest_product_candidates(
                req.question, reader, req.workspace_id, exclude=session.product_name,
                alias_map=alias_map,
            )
            if suggestions:
                logger.info(
                    "cpq_switch: ambiguous product mention turn=%s current=%r suggestions=%r",
                    session.turn, session.product_name, suggestions,
                )
                # The hint question MUST set a pending state its reply can be
                # matched against (Issue 7): the stateless version of this
                # prompt let a "yes" reply fall through to the approval
                # handler, which SUBMITTED the current quote the user was
                # trying to switch away from (confirmed live). One candidate
                # → the existing confirm_switch gate handles yes/no (and its
                # country re-validation); several → suggest_switch, whose
                # gate re-prompts on a bare "yes" instead of guessing.
                if len(suggestions) == 1:
                    session.pending_switch_product = suggestions[0]
                    session.pending_anchor = "confirm_switch"
                    answer = (
                        f"I couldn't tell if that's a different product — did you "
                        f"mean **{suggestions[0]}**? Switching would discard the "
                        f"current **{session.product_name}** configuration. (yes/no)"
                    )
                else:
                    session.pending_switch_candidates = suggestions
                    session.pending_anchor = "suggest_switch"
                    sug_list = ", ".join(f"**{s}**" for s in suggestions)
                    answer = (
                        f"I couldn't tell if that's a different product — did you "
                        f"mean one of: {sug_list}? Reply with the product name, or "
                        f"say **no** to continue with **{session.product_name}**."
                    )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_switch_ambiguous()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }

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

    if not attrs:
        return {}  # no CPQ data in graph — fall through to standard Ask

    # Catalog-aware hints — now that attrs (and their real options) are
    # loaded, scan the question for real option text extract_hints()'s fixed
    # 3-concept pattern list has no coverage for (battery, multikey, carry
    # solution, DMS tier, ...). setdefault so the curated patterns still win
    # where both mechanisms independently find the same attr.
    # catalog_prefix scopes every rule/function load to the same ingested
    # catalog attrs came from, so a workspace holding more than one
    # product's XML export never lets one catalog's rules act on another's
    # attributes (see CpqEngine._scope_to_catalog).
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    # Option-less fields a real BML script checks (e.g. customerType) that
    # extract_catalog_hints can never reach — see CpqEngine.extract_flag_hints.
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    # Accumulate across turns (not just this one) — see CpqSession.negated_vns.
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    # Seed the punch-in model context when the catalog's own bm_catalog
    # tree makes it unambiguous (exactly one model leaf — SVX's vX650_BOM).
    # BM injects _bm_model_variable_name at runtime; exports never carry
    # it, which is why modelname_all (whose XML default POINTS at it)
    # shipped the literal token in payloads (Issue 11). The hint fills the
    # noise-prefixed context attr (feeds BML scripts, never the payload),
    # and auto_fill's pointer post-pass resolves modelname_all from it.
    # Ambiguous trees (APX Next: two model leaves) seed nothing.
    model_vn = _cpq_engine.single_model_variable_name(
        reader, req.workspace_id, catalog_prefix)
    if model_vn:
        hints.setdefault("_bm_model_variable_name", model_vn)

    # ── Load all rule sets (needed for Step 3, 5, 6, 7) ───────────────────────
    hiding_rules = _cpq_engine.load_hiding_rules(req.workspace_id, catalog_prefix)
    rec_rules, con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, catalog_prefix)
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    # Rule-consistency auto-fix (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    # §4.1): a filled attr an active hiding rule currently matches was never
    # a real customer decision — drop it from every build_payload call this
    # turn rather than silently submitting it. Computed once here since
    # hiding_rules/bml_eval are already loaded and this turn's `filled`
    # doesn't change again until the next request.
    _hidden_for_payload = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval)[2]
    # Skipping the always-ask override (resolve_always_ask_skips) stops the
    # QUESTION, but auto_fill's normal fallback still assigns the attr some
    # value (first-by-order/default) since no rule governs it either — and
    # for a catalog where the real native UI never shows this field at all,
    # that guessed value has no business in the submitted payload (confirmed
    # live: SVX's productSelectionProduct_all fell back to "APX6500", an
    # unrelated APX Next radio model). Same exclusion set, same reasoning as
    # hiding-rule auto-fix above — union both into one payload-drop set.
    # payload_flow_exclusions adds product/model mutual exclusivity on top
    # of the always-ask skips: model flow drops the product selector,
    # product flow drops the model-context mirrors (see its docstring).
    _hidden_for_payload = _hidden_for_payload | _cpq_engine.payload_flow_exclusions(
        req.workspace_id, catalog_prefix, attrs)
    # Constraint/recommendation-type inconsistencies (same plan, §4.1) are
    # NOT auto-fixed — unlike hiding, the engine can't be certain what the
    # correct value should have been, so silently changing it risks
    # overwriting a real customer choice. Logged only, for now, as the
    # audit trail this plan requires; surfacing it to the user directly
    # is a separate, not-yet-built follow-up.
    _rule_issues = _cpq_engine.find_rule_inconsistencies(
        session.filled, attrs, hiding_rules, con_rules, rec_rules, bml_eval,
        filled_source=session.filled_source)
    if _rule_issues:
        logger.info(
            "cpq: rule-consistency check found %d issue(s): %s",
            len(_rule_issues), _rule_issues,
        )
    # Array-grid controls (e.g. a mounting-type quantity grid) — flagged,
    # never auto-populated: the real row->quantity link lives only in
    # BigMachines' own native-UI array-control widget, not in any ingested
    # rule data (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5).
    _array_grid_vns = _cpq_engine.array_grid_controls_in_play(attrs)
    if _array_grid_vns:
        logger.info(
            "cpq: array-grid control attr(s) present, not auto-populated "
            "(no rule data links row selection to quantity attrs): %s",
            _array_grid_vns,
        )

    # ── STEP 6 / 7 / 8 routing: awaiting_approval status ────────────────────
    if session.status == "awaiting_approval":
        # Explicit JSON request while awaiting approval — checked BEFORE
        # approval/Q&A/change detection so "show me the json" is never
        # misread as one of those (same reasoning as the early mode_request
        # check in the configuring flow below). JSON stays on-demand only —
        # this does not submit anything, cpq_payload stays unset.
        if _cpq_engine.detect_response_mode_request(req.question) == "json":
            preview_payload = _cpq_engine.build_payload(
                session.filled, session.filled_source, session.filled_multi, attrs,
                hidden_vns=_hidden_for_payload)
            rule_ids_preview = _cpq_engine.rule_governed_ids(
                attrs, hiding_rules, rec_rules, con_rules)
            summary = _cpq_summary_text(
                session.display_filled, attrs, rule_ids_preview,
                session.product_name, req.workspace_id,
            )
            answer = (
                (f"{summary}\n\n" if summary else "")
                + f"Here's the full configuration for **{session.product_name}** — "
                  f"**preview, not final**:\n\n"
                f"```json\n{json.dumps(preview_payload, indent=2)}\n```\n\n"
                f"Say **confirm** to submit, or describe any changes."
            )
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_json_preview()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                "preview": True,
            }

        # STEP 8: explicit approval → generate BOM payload
        if _cpq_engine.detect_approval(req.question):
            session.status = "approved"
            session.complete = True
            payload = _cpq_engine.build_payload(
                session.filled, session.filled_source, session.filled_multi, attrs,
                hidden_vns=_hidden_for_payload)
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
        change_result = _cpq_engine.detect_change_request(
            req.question, attrs, session.filled, filled_multi=session.filled_multi)
        if change_result:
            changed_attr, new_value_hint = change_result
            return _handle_cascade(
                req, session, attrs, changed_attr, new_value_hint,
                hiding_rules, rec_rules, con_rules,
            )

        # Could not parse as approval, Q&A, change, or JSON request — nudge
        # with the verbose summary, NOT the raw JSON (§6/Phase K: JSON stays
        # on-demand only; misreading input isn't a request for it).
        rule_ids_nudge = _cpq_engine.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
        summary = _cpq_summary_text(
            session.display_filled, attrs, rule_ids_nudge,
            session.product_name, req.workspace_id,
        )
        answer = (
            f"I didn't quite catch that. Here is the current configuration for "
            f"**{session.product_name}**:\n\n"
            + (f"{summary}\n\n" if summary else "")
            + f"Click **JSON** below to see the full payload, "
              f"say **confirm** to submit, or describe what to change."
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
    # `and not mode_request`: an explicit JSON/batch request must win here too,
    # same as it does over Step 5 below — otherwise a batch request starting
    # with "what" (e.g. "what else do you need from me") is misread as a
    # Q&A question instead of the batch-listing request it actually is.
    if session.pending_variables and session.turn > 1 and not mode_request:
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
            # Constraints active when this attr was presented last turn —
            # session.filled hasn't changed since then (this turn's answer
            # is applied below), so recomputing now reflects exactly what
            # the user was shown (Phase I).
            pending_constrained = _cpq_engine.apply_constraint_rules(
                attrs, con_rules, session.filled, bml_eval=bml_eval,
            ).get(pending_attr.entity_id)
            # Try the user's full utterance first — they may have typed the exact
            # option name (e.g. "APX NEXT (4G LTE+5G)"). Only fall back to the
            # extracted hint if the full question produces no match; hints are
            # coarse (e.g. "LTE") and can mis-match when multiple options share
            # the same keyword.
            if pending_attr.select_type == "multi":
                # A multi-select answer can name several options at once
                # (e.g. "Shirt Magnetic Mount, Jacket Magnetic Mount, ...") —
                # apply_answer() only ever returns the single best match, so
                # naming all 6 real mounting-type options in one answer
                # previously captured just 1 (confirmed live). Scan for every
                # option mentioned instead.
                multi_matches = _cpq_engine.apply_multi_answer(
                    pending_attr, req.question, pending_constrained)
                if not multi_matches and hint_val_for_attr:
                    multi_matches = _cpq_engine.apply_multi_answer(
                        pending_attr, hint_val_for_attr, pending_constrained)
                result = multi_matches[0] if multi_matches else None
            else:
                result = _cpq_engine.apply_answer(pending_attr, req.question, pending_constrained)
                if not result and hint_val_for_attr:
                    result = _cpq_engine.apply_answer(pending_attr, hint_val_for_attr, pending_constrained)
            if result:
                iv, disp = result
                if pending_attr.select_type == "multi":
                    # Every option apply_multi_answer() found in this answer
                    # is a real selection — store as a single-item list in
                    # filled_multi, not a scalar in filled, so build_payload
                    # serializes it as the array the real CPQ API expects
                    # for these attrs (confirmed live: nothing was ever
                    # classified "multi" before the display_type/attr_type
                    # reclassification, so this branch was previously dead
                    # code — now that real attrs reach it, storing a
                    # multi-select answer as a scalar would silently defeat
                    # that fix for every attr answered directly rather than
                    # auto-filled).
                    existing = session.filled_multi.get(pending_var, [])
                    for match_iv, _match_disp in multi_matches:
                        if match_iv not in existing:
                            existing = [*existing, match_iv]
                    session.filled_multi[pending_var] = existing
                    session.display_filled[pending_var] = ", ".join(
                        next((o.display_name for o in pending_attr.options
                              if o.item_value == v), v)
                        for v in existing
                    )
                    session.filled_source[pending_var] = "user"
                else:
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
            elif (pending_attr.select_type == "multi"
                    and not pending_attr.required
                    and re.match(r"^\s*(no|none|nope|skip|nothing|not\s+needed)\b",
                                 req.question.strip().lower())):
                # Explicit decline of an OPTIONAL multi-select (e.g. the
                # mount-type quantity grid: required="0" in the raw XML,
                # and the real native UI lets the grid stay empty).
                # Previously "no mounts needed" was rejected and the same
                # question re-asked forever — the only escape was picking
                # a mount the customer didn't want. An empty selection IS
                # the answer: record it as user-confirmed so auto_fill
                # never re-resolves or re-asks it, and the payload simply
                # carries no rows (build_payload already skips empty
                # values). Checked ONLY after apply_answer found no option
                # match, so option names are never misread as declines,
                # and never offered for required multi-selects.
                session.filled_multi[pending_var] = []
                session.display_filled[pending_var] = "(none)"
                session.filled_source[pending_var] = "user"
                logger.info(
                    "cpq: optional multi-select %r explicitly declined turn=%s",
                    pending_var, session.turn,
                )
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
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, rule_governed_ids=rule_ids, country=session.country,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask,
    )
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)
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
        k: v for k, v in session.filled_source.items()
        if k in filled or k in session.filled_multi
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
        # ── STEP 6: FORMAT B — verbose summary, JSON only on request ─────────
        # (§6/Phase K: JSON is never shown unasked, even at completion —
        # only the earlier "still configuring" responses honored this
        # before; this branch previously dumped the full BOM immediately.)
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id,
        )
        answer = (
            (f"{dropped_note.strip()}\n\n" if dropped_note else "")
            + f"Configuration complete for **{session.product_name}**.\n\n"
            + (f"{summary}\n\n" if summary else "")
            + f"Click **JSON** below to see the full payload, "
              f"say **confirm** to submit, or describe any changes."
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
            # Recomputed against the CURRENT `filled` (post-cascade), not the
            # turn-start `_hidden_for_payload` — cascades earlier in this
            # same turn can change which hiding rules are active.
            _hidden_now = _cpq_engine.apply_hiding_rules(attrs, filled, hiding_rules, bml_eval)[2]
            _hidden_now = _hidden_now | _cpq_engine.payload_flow_exclusions(
                req.workspace_id, catalog_prefix, attrs)
            preview_payload = _cpq_engine.build_payload(
                filled, session.filled_source, session.filled_multi, visible_attrs,
                hidden_vns=_hidden_now)
            summary = _cpq_summary_text(
                display_filled, visible_attrs, rule_ids,
                session.product_name, req.workspace_id,
            )
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


# Readiness gate for the JSON/Beautify/Share buttons: don't expose them
# until there's enough substance to be worth showing (3 answered attrs),
# or the session has already reached review/approval regardless of count.
_SHARE_READY_MIN_FILLED = 3


def _attach_share_flags(result: dict[str, Any], req: "AskRequest", reader: Any) -> None:
    """Splice json/beautify/api_share fields into a CPQ turn's response, in place.

    Single wrap point (called once from run_ask, not from every _run_cpq_turn
    return site) — recomputed every ready turn from current session state, never
    cached, since cascade can invalidate previously-filled attrs mid-conversation.
    """
    session_data = result.get("session_data")
    if not session_data:
        return
    session = CpqSession.from_dict(session_data)
    filled_count = len(session.filled) + len(session.filled_multi)
    ready = filled_count >= _SHARE_READY_MIN_FILLED or session.status != "configuring"
    if not ready or not session.product_name:
        return
    attrs, _ = _cpq_engine.load_product_config(reader, req.workspace_id, session.product_name)
    # NOTE: hiding-rule auto-fix (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    # §4.1) is not applied here — this is only the share-button preview
    # snapshot, and loading hiding_rules/bml_eval here would mean a second
    # rule-fetch round trip on every ready turn just for a preview. The real
    # submission path (_run_cpq_turn's Step 8 build_payload call) already
    # applies it.
    # Flow exclusions MUST apply here too (Issue 11 §5) — this is the web
    # UI's JSON-button payload, a separate emission path from the chat
    # "show me the json" preview and the Step-8 submission (both already
    # excluded). Confirmed live: without this, the button showed
    # modelname_all alongside productSelectionProduct_all (and, on model
    # flows, the skipped product selector). Cheap: layout scope is cached
    # per (workspace, catalog); no extra rule fetch.
    flow_exclusions = _cpq_engine.payload_flow_exclusions(
        req.workspace_id, attrs[0].catalog_prefix if attrs else "", attrs)
    payload = _cpq_engine.build_payload(
        session.filled, session.filled_source, session.filled_multi, attrs,
        hidden_vns=flow_exclusions)
    result["json_response"] = payload
    result["json_button_flag"] = True
    result["beautify"] = _cpq_engine.beautify_text(session.product_name, session.display_filled, attrs)
    result["beautify_rows"] = _cpq_engine.beautify_rows(session.product_name, session.display_filled, attrs)
    result["beautify_button_flag"] = True
    result["api_share"] = payload if session.status != "configuring" else {}
    result["api_share_button_flag"] = session.status != "configuring"


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
        or _cpq_engine.is_cpq_question(req.question, reader, req.workspace_id)
    )
    if is_cpq:
        result = _run_cpq_turn(req, reader)
        if result:  # non-empty → CPQ engine handled it
            _attach_share_flags(result, req, reader)
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
