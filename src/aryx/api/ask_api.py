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
from aryx.cpq.engine import CpqEngine, DECISION_REQUIRED_KEYS, SUMMARY_FALLBACK_CATEGORY
from aryx.cpq.bom_gate import validate_before_payload
from aryx.cpq.intent_gateway import (
    AskRouteDecision,
    classify_ask_route,
    classify_intent as gateway_classify_intent,
    hard_off_topic,
    mark_top_level_route_used,
    soft_quote_heuristic,
    top_level_route_used,
)
from aryx.cpq.intent_schema import (
    ChangeTarget,
    Confidence,
    INTENT_RESULT_JSON_SCHEMA,
    IntentCategory,
    IntentResult,
    parse_intent_result,
)
from aryx.cpq.logging_context import install_run_id_logging, set_run_id
from aryx.cpq.session_guard import (
    audit_intent_conservation,
    clear_clarify,
    clear_queue_vn,
    detect_guided_mode_accept,
    detect_undo,
    drain_intent_queue_into_pending,
    enforce_conversational_invariant,
    enqueue_intent_targets,
    format_dropped_intent_notice,
    format_queue_overflow_notice,
    guided_mode_offer_message,
    note_clarify,
    numbered_options_prompt,
    push_snapshot,
    record_utterance,
    restore_last_snapshot,
    should_force_numbered_options,
    should_offer_guided_mode,
    undo_empty_message,
    undo_success_message,
)
from aryx.cpq.pending_scope import (
    candidates_from_attr_options,
    clear_pending_scope,
    format_did_you_mean,
    log_scope_lost,
    log_scope_retained,
    resolve_against_scope,
    scope_loop_exit_threshold,
    set_pending_scope,
)
from aryx.cpq.replacement_clause import extract_replacement_clause
from aryx.cpq.state import INTENT_QUEUE_CAP, ConfigAttr, CpqSession, MenuOption
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
            cur.execute(load("select_workspace_by_id"), (workspace_id,))
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


_HISTORY_MINE_LIMIT = 8


def _user_texts_from_history(
    history: list[Turn], limit: int = _HISTORY_MINE_LIMIT,
) -> list[str]:
    """User-role utterances from Ask history (oldest → newest within window)."""
    if not history:
        return []
    out: list[str] = []
    for t in history[-limit:]:
        role = (getattr(t, "role", None) or "").lower()
        text = (getattr(t, "text", None) or "").strip()
        if not text:
            continue
        # Treat empty role as user; clients sometimes omit role on user turns.
        if role in ("", "user", "human", "h", "customer"):
            out.append(text)
    return out


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
    texts = _user_texts_from_history(history)
    if not texts:
        return

    from aryx.cpq.intent_gateway import soft_quote_heuristic

    # Prefer the longest order-like utterance for product_anchor_question.
    order_candidates = [
        t for t in texts
        if soft_quote_heuristic(t) or engine.extract_hints(t).get("country")
    ]
    if order_candidates:
        best = max(order_candidates, key=len)
        prior = session.product_anchor_question or ""
        if not prior or len(best) > len(prior):
            session.product_anchor_question = best
            logger.info(
                "cpq: mined product_anchor_question from history (%d chars)",
                len(best),
            )

    if session.country:
        return

    # Newest country mention wins (scan history newest-first).
    for text in reversed(texts):
        country = engine.extract_hints(text).get("country")
        if country:
            session.country = country
            logger.info(
                "cpq: mined country=%r from Ask history (pre-CPQ turn)",
                country,
            )
            return


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
# Segments _cpq_summary_text asks the LLM to separate its reply by — one
# lead-in sentence + one narration segment per category, code-assembled
# with the real "• Category" headers afterwards (see _cpq_summary_text).
# Distinctive enough that real narration text won't produce it by accident.
_CPQ_SEGMENT_DELIM = "@@@"


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
                workspace_id: int = 1, session_values: str = "") -> tuple[str, int, int, int]:
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

    # Grounded scope check (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 2, extended
    # 2026-07-28): originally only spent when GRAPH FACTS was empty. Confirmed
    # live this codepath previously fabricated plausible-sounding catalog
    # details (SVX Video RSM, currency options) for a genuinely unrelated
    # astrology question ("astra in astrological sense") — but that fabricated
    # answer came from a WEAK/SPURIOUS entity match the graph search DID
    # return (has_context was True), not from an empty result, so the
    # original has_context-gated check never even ran. The catalog-relevance
    # question ("is this question actually about product config/quoting at
    # all?") is independent of whether SOME entity happened to fuzzy-match —
    # always classify, and let a genuinely irrelevant question override
    # whatever facts were found.
    # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §14 — pass the
    # recent conversation (already computed above as `conv`) so a mid-
    # session follow-up like "what is the error" can be recognized as
    # relevant when the prior turn was the engine's own gate error. The
    # OTHER call site (run_ask's fresh-turn router) intentionally does not
    # pass this — it has no session context to give. Ported onto
    # _llm_classify_is_ask_in_scope (not _llm_classify_is_cpq_question) —
    # this call site needs the BROADER scope gate (general enterprise/
    # catalog questions, not just quote/order intent); see that function's
    # own docstring for why reusing the narrow classifier here caused Ask
    # to refuse almost every question.
    is_cpq_relevant = _llm_classify_is_ask_in_scope(
        question, workspace_id, prior_context=conv,
    )
    logger.info(
        "cpq_qa_scope: has_context=%s for %r -> is_ask_in_scope=%s",
        has_context, question, is_cpq_relevant,
    )

    if not is_cpq_relevant:
        empty_rule = (
            "- The question is not about product configuration, quoting, or "
            "enterprise data at all → say plainly that this is outside what "
            "you track (product configuration and quoting), in one short "
            "sentence, EVEN IF something below happens to loosely match a "
            "word in the question. Do NOT invent or connect unrelated "
            "catalog details to answer it anyway.\n"
        )
    elif has_context:
        empty_rule = (
            "- GRAPH FACTS present → answer specifically, naming the entities, "
            "values, and relationships shown, in plain language.\n"
        )
    else:
        empty_rule = (
            "- GRAPH FACTS empty → use the OVERVIEW to describe what IS tracked "
            "and suggest a concrete follow-up question. "
            "Do NOT say 'no matching entities' or 'not stored'.\n"
        )

    # Session-value rule (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 3): only
    # added when the caller found a real filled value for an entity the
    # graph search resolved. Confirmed live this path previously answered
    # "the data doesn't show a specific frequency value being set" for a
    # question about an attr that WAS genuinely filled in this exact
    # session — GRAPH FACTS alone is the static catalog schema, never the
    # per-turn answered values, so this couldn't be told apart from
    # genuinely unfilled without this.
    session_values_block = ""
    session_value_rule = ""
    if session_values.strip():
        session_values_block = f"\nSESSION VALUES:\n{session_values}\n"
        session_value_rule = (
            "- If the question asks what something is currently SET TO, "
            "answer from SESSION VALUES when present — it reflects this "
            "customer's real selection for THIS quote, which the static "
            "GRAPH FACTS alone cannot show.\n"
        )

    user = (
        "Answer the QUESTION using the evidence below.\n\n"
        "Rules:\n"
        f"{session_value_rule}"
        f"{empty_rule}"
        "- Do NOT invent facts not shown in GRAPH FACTS.\n"
        "- Use CONVERSATION SO FAR to resolve pronouns and give continuity.\n"
        f"- Format: maximum {_MAX_ANSWER_LINES} lines. Lead with a direct "
        "one-line answer, then supporting detail in the order a person would "
        "naturally explain it. Use a short list only when multiple distinct "
        "items are being enumerated. Plain, everyday English — no technical "
        "or internal terms.\n\n"
        f"{overview}{conv_block}{session_values_block}\nGRAPH FACTS:\n"
        f"{facts if is_cpq_relevant else '(withheld — question is off-topic, see rule above)'}"
        f"\n\nQUESTION: {question}"
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
    sources: dict[str, str] | None = None,
) -> str:
    """Structured, headed/bulleted summary of the filtered configuration.

    Post-generation, summary_guard diffs field-by-field against session
    display state; mismatch regenerates once, then falls back to the raw
    state table (never a hallucinated summary).

    The engine's `categorized_summary_groups` owns ALL filtering (booleans,
    secondary/warranty/product attrs, year durations, rule-governed set,
    "(none)" placeholders) AND the same category grouping (Product Name /
    Service Plan / Quantity & Duration / Associated Options, or however
    many are actually present) the deterministic fallback
    (`render_filled_summary`) uses.

    The "**Category:**" headers are assembled here in CODE, never left to
    the LLM to reproduce verbatim — asking a model to keep exact header
    text on its own line is a request, not a guarantee (confirmed live: it
    silently folded headers into running prose instead of respecting the
    line breaks). The model is only asked for each category's CONTENT — its
    real bulleted/plain-text shape (bullets for every category except
    Associated Options, one plain-text line for that one) — as one segment
    per category separated by a fixed delimiter it cannot plausibly emit as
    part of real prose, so the structure is deterministic while the wording
    stays LLM-narrated. Associated Options is explicitly told to OMIT any
    fact it isn't sure of rather than gesture at it with a vague placeholder
    (e.g. never "plus the usual defaults") — confirmed live to hallucinate
    otherwise. If the reply doesn't split into exactly the expected number
    of segments, or the LLM call fails/returns empty, this falls back to
    `render_filled_summary` — the CPQ flow must never block on, or silently
    mis-format via, the narrator.
    """
    groups = _cpq_engine.categorized_summary_groups(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    if not groups:
        return ""
    # The narrator and its bullet fallback are only ever asked to cover
    # THESE curated (label, value) facts — never the raw display_filled
    # dict, which includes hundreds of internal/technical BM fields
    # (Record Separator, BoolContinue1-4, HTML Update1-3, etc.) neither
    # synthesis path is designed to mention. Validating against raw
    # display_filled instead of this set made the check structurally
    # unsatisfiable for any product with many such fields — a correct
    # summary that (rightly) omits them got discarded every time,
    # falling all the way to raw_state_table(). Live-confirmed against
    # aSTRO25_bom / APX NEXT Single Band (~173 auto-filled fields).
    # Only the STRICT categories (Product Name, Service Plan, Quantity &
    # Duration) are required to be fully covered. The fallback category
    # (Associated Options) is deliberately excluded here — the prompt
    # below explicitly tells the model it may OMIT facts in that one
    # category ("pick whichever subset you can state with total accuracy
    # and simply OMIT the rest"), so requiring every one of its facts to
    # appear contradicts the very permission the prompt grants, and
    # discarded a correct, intentionally-partial narration every time
    # (live-confirmed: aSTRO25_bom / APX NEXT Single Band's Associated
    # Options narration was rejected for omitting Primary Frequency,
    # Keypad Type, Display Type, Knob Type, System Key — all deliberately
    # dropped by design, not missing by error).
    curated_fields = {
        label: value for _cat, pairs in groups
        if _cat != SUMMARY_FALLBACK_CATEGORY
        for label, value in pairs
    }
    sys = (
        "You summarise product configurations for sales reps in plain, "
        "everyday English — never technical or internal terminology."
    )
    config_text = "\n\n".join(
        f"{category}:\n"
        + "\n".join(f"- {label}: {value}" for label, value in pairs)
        for category, pairs in groups
    )
    expected_segments = 1 + len(groups)
    user = (
        f"Describe this {product_name or 'product'} configuration for a sales "
        f"rep. Reply with EXACTLY {expected_segments} segments separated by "
        f"the literal token {_CPQ_SEGMENT_DELIM} (nothing else on the "
        f"delimiter's line) — never merge two segments together, never add "
        "or omit a segment, never include this instruction or the token "
        "anywhere except as a separator.\n\n"
        "Segment 1: one direct sentence, e.g. 'Your configuration is complete.'\n"
        + "\n".join(
            (
                f"Segment {i + 2}: the {category} facts below as short markdown "
                "bullets '- **Label** → value', one bullet per fact, using "
                "plain-English labels instead of raw variable names."
                if category != SUMMARY_FALLBACK_CATEGORY
                else (
                    f"Segment {i + 2}: ONE short plain-text line narrating the "
                    f"{category} facts below (not a bulleted list, not "
                    "'label: value' pairs) — you do not need to mention every "
                    "fact in this category; pick whichever subset you can "
                    "state with total accuracy and simply OMIT the rest. Never "
                    "paraphrase, generalise, or invent a placeholder for a "
                    "fact you are dropping (e.g. never write anything like "
                    "'plus the usual defaults') — an omitted fact must be "
                    "invisible, not gestured at."
                )
            )
            for i, (category, _pairs) in enumerate(groups)
        ) + "\n\n"
        "Use ONLY the exact facts below; if you are not certain a name or "
        "value is precisely what you are about to write, leave it out "
        "rather than guess or approximate it.\n\nCONFIGURATION:\n" + config_text
    )
    try:
        # ARYX_LLM_REASON_MODEL (role="answer"), not menial — this narration
        # is the customer-facing summary of a real quote; the same reasoning
        # tier already used for CPQ's own BML Tier-2 script fallback.
        text, _it, _ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
        text = _strip_think(text).strip()
        segments = [s.strip() for s in text.split(_CPQ_SEGMENT_DELIM)]
        if len(segments) == expected_segments and all(segments):
            lead_in = _SENTENCE_SPLIT.split(segments[0])[0].strip()
            lines = [lead_in]
            for (category, _pairs), segment in zip(groups, segments[1:]):
                if category == SUMMARY_FALLBACK_CATEGORY:
                    # Meant to be one short line already (per the prompt) —
                    # still cap to the first sentence so a model that rambles
                    # anyway can't blow past the "plain-text line" contract.
                    segment = _SENTENCE_SPLIT.split(segment)[0].strip()
                # Every other category is real bullet lines, one per fact —
                # capping to "first sentence" here would truncate to a
                # single bullet, so the full segment is kept verbatim.
                lines.append(f"\n**{category}:**\n{segment}")
            draft = "\n".join(lines)
            # summary_guard: every CURATED value (curated_fields, not the
            # raw display_filled dict) must appear in the narration
            from aryx.cpq.summary_guard import (
                fields_missing_from_summary, raw_state_table,
            )
            missing = fields_missing_from_summary(draft, curated_fields)
            if not missing:
                return draft
            logger.info(
                "summary_guard: LLM summary missing %s — regenerating via "
                "deterministic bullets", missing[:5],
            )
            second = _cpq_engine.render_filled_summary(
                display_filled, attrs, rule_governed_ids=rule_governed_ids,
                sources=sources,
            )
            missing2 = fields_missing_from_summary(second, curated_fields)
            if not missing2:
                return second
            logger.warning(
                "summary_guard: deterministic bullet fallback ALSO missing "
                "%s — falling back to raw_state_table", missing2[:5],
            )
            stub = CpqSession()
            stub.display_filled = dict(display_filled)
            stub.filled_source = dict(sources or {})
            return raw_state_table(stub, attrs)
        logger.debug(
            "cpq: summary narration returned %d segments (expected %d) — "
            "using bullet fallback", len(segments), expected_segments)
    except Exception:  # noqa: BLE001
        logger.debug("cpq: summary narration failed — using bullet fallback",
                     exc_info=True)
    return _cpq_engine.render_filled_summary(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)


def _build_attr_options_text(
    req: "AskRequest", session: Any, attrs: list, attr_q: Any,
) -> str | None:
    """Build "The available options for X are: ..." text for one already-
    resolved attribute, constrained to the currently-active allowed set.
    Returns None when the attribute has no presentable options at all.

    Factored out of `_handle_cpq_qa`'s single-attr fast path (docs/
    config_consistency_issues_2026-07-30.md issue 3) so the same constrained-
    options logic can answer more than one attribute in one turn — a
    customer asking about 2+ different attributes must get both answered,
    not have `detect_attr_query`'s single-best-match nature silently drop
    the second one.
    """
    _presentable = [o for o in attr_q.options if o.display_name.strip()]
    if not _presentable:
        return None
    # Constrain to values compatible with what's already selected
    # (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related finding 2 —
    # confirmed live: this Q&A fast path, exercised once the config is
    # already awaiting_approval, listed all 325 raw Product codes instead
    # of the ~2 an active constraint rule actually allows; the first fix
    # attempt only patched _run_cpq_turn's OWN separate options-query
    # block, which isn't the one reached here).
    _qa_catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    _, _qa_con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, _qa_catalog_prefix)
    _qa_bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, _qa_catalog_prefix)
    _qa_constrained = _cpq_engine.apply_constraint_rules(
        attrs, _qa_con_rules, session.filled, _qa_bml_eval)
    _qa_allowed = _qa_constrained.get(attr_q.entity_id)
    if _qa_allowed is not None:
        _presentable = [o for o in _presentable if o.item_value in _qa_allowed]
    _numbered = "\n".join(
        f"{i + 1}. {o.display_name}" for i, o in enumerate(_presentable)
    )
    return (
        f"The available options for **{_cpq_engine.disambiguated_label(attr_q, attrs)}** "
        f"are:\n\n{_numbered}"
    )


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
    # Label collision check first — a shared display_label across 2+ distinct
    # attrs (real BigMachines source-data reuse, docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 2) must be disambiguated, never silently resolved to whichever
    # attr happens to be first in list order.
    _collision = _cpq_engine.detect_label_collision(req.question, attrs)
    if _collision:
        _collision = _narrow_label_collision(req.question, _collision)
        _lines = "\n".join(
            f"- **{a.variable_name}**"
            f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
            for a in _collision
        )
        qa_answer = (
            f"There are {len(_collision)} different attributes labeled "
            f"**\"{_collision[0].display_label}\"** in this catalog — which one "
            f"did you mean?\n\n{_lines}"
        )
        # Remembered so the NEXT turn's reply (a bare variable_name, a list
        # index, or looser phrasing an LLM fallback resolves — see
        # _run_cpq_turn's resolution block) answers THIS prompt instead of
        # being read as an unrelated message (live-verified gap,
        # 2026-07-23 — same class of bug already fixed for the
        # change-request collision via pending_change_collision_vns).
        session.pending_label_collision_vns = [a.variable_name for a in _collision]
        session.pending_label_collision_question = req.question
        _persist_cpq_history(req.workspace_id, req.question, qa_answer)
        return {
            "answer": qa_answer, "terms": [], "tools_called": ["cpq_label_collision()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # docs/config_consistency_issues_2026-07-30.md issue 3 — compound
    # multi-attribute options query, must run BEFORE the single-attr fast
    # path below: detect_attr_query only ever returns ONE best match, so
    # "what are the Frequency Bands and Wireless Carrier available?" would
    # otherwise silently answer just one and drop the other (or, before the
    # detect_label_collision grouping fix above, get wrongly treated as a
    # 3-way label collision — a different, deterministic bug; this one is
    # a customer genuinely naming 2+ real, unambiguous attributes at once).
    # LLM-first, gated behind a cheap options-keyword + conjunction
    # pre-check so the common single-attribute case never pays this call.
    if (
        any(kw in req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)
        and (" and " in f" {req.question.lower()} " or "," in req.question)
    ):
        _multi_qs = _llm_split_multi_attr_options_query(
            req.question, attrs, req.workspace_id,
        )
        if _multi_qs:
            _multi_answers = []
            for _sub_q in _multi_qs:
                _sub_attr = _cpq_engine.detect_attr_query(_sub_q, attrs)
                _sub_answer = (
                    _build_attr_options_text(req, session, attrs, _sub_attr)
                    if _sub_attr else None
                )
                if _sub_answer:
                    _multi_answers.append(_sub_answer)
                    session.last_qa_variable = _sub_attr.variable_name
            if len(_multi_answers) >= 2:
                qa_answer = "\n\n".join(_multi_answers)
                _persist_cpq_history(req.workspace_id, req.question, qa_answer)
                return {
                    "answer": qa_answer, "terms": [],
                    "tools_called": ["cpq_multi_attr_options()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            # Fewer than 2 of the split questions actually resolved to a
            # real attribute — fall through to the single-attr fast path
            # unchanged rather than returning a half-answered response.

    # Fast path: question asks about a specific attribute's available options.
    # Uses attr.options already in memory from BmMenuItem — no graph query,
    # no LLM synthesis, no schema leakage possible.
    _attr_q = _cpq_engine.detect_attr_query(req.question, attrs)
    qa_answer = _build_attr_options_text(req, session, attrs, _attr_q) if _attr_q else None
    if qa_answer:
        # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §8: remember
        # what the customer just asked about so a follow-up bare-value reply
        # ("make it ATT/FirstNet") can be preferred toward THIS attribute
        # even when a sibling attribute genuinely shares the same option value.
        session.last_qa_variable = _attr_q.variable_name
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
            # Session values (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 3):
            # entities found here come from the STATIC catalog graph only —
            # confirmed live this path answered "the data doesn't show a
            # specific value being set" for an attr that WAS genuinely
            # filled this session, because session.filled was never
            # cross-referenced. Only inject values for entities THIS
            # search already found relevant (never the whole filled dict)
            # — a ConfigAttr entity's graph id IS its entity_id, same
            # convention used throughout this file.
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
            # clarifying question instead of committing to one
            # interpretation, BEFORE synthesising an answer from whatever
            # graph_search returned. Gated on cpq_qa_ambiguity_check_enabled
            # (default off, same test-speed/CI-cost reasoning as the other
            # Phase 1/2 flags). Reuses the SAME universal classifier as
            # Phase 1/2 — its AMBIGUOUS category + clarifying_question is
            # exactly the "ask before guessing, even a single word" output
            # this was designed to produce; this is simply its first REAL
            # (non-shadow) consumer, scoped to informational Q&A only
            # (never config-mutating, so a wrong call here just means one
            # extra clarifying question, not a misapplied change).
            _qa_ambiguity_answer = None
            _qa_it = _qa_ot = 0
            if get_settings().cpq_qa_ambiguity_check_enabled:
                try:
                    _qa_intent, _qa_it, _qa_ot = _llm_classify_intent_universal(
                        req.question, attrs, session, req.workspace_id)
                    if (
                        _qa_intent is not None
                        and _qa_intent.category == IntentCategory.AMBIGUOUS
                        and _qa_intent.confidence != Confidence.LOW
                        and _qa_intent.clarifying_question
                    ):
                        _qa_ambiguity_answer = _qa_intent.clarifying_question
                except Exception:  # noqa: BLE001 — must never break the Q&A turn
                    logger.debug("cpq_qa_ambiguity: check failed", exc_info=True)
            if _qa_ambiguity_answer is not None:
                qa_answer = _qa_ambiguity_answer
                # p_in/p_out/p_ms already reflect the real _extract_terms
                # call above -- s_in/s_out here report the classification
                # call's own real usage (2026-07-28), not zero, since a
                # real LLM call drove this answer (the _synthesise call
                # this branch skips is what would have otherwise reported).
                s_in, s_out, s_ms = _qa_it, _qa_ot, 0
            else:
                qa_answer, s_in, s_out, s_ms = _synthesise(
                    req.question, context, history=req.history, workspace_id=req.workspace_id,
                    session_values=session_values,
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


def _append_unmatched_targets_note(
    result: dict, question: str, attrs: list, matched_vns: "set[str]",
) -> dict:
    """Surfaces (never silently drops) a fragment of a multi-target change
    request that named nothing real — live-verified gap: "change solution
    type and hardware type" successfully changed Solution Type but said
    nothing at all about "hardware type" (which names no real attr in
    this catalog), leaving the customer unable to tell whether it was
    understood-and-ignored or simply forgotten. Called at every STEP 6
    change-request dispatch site right after the real change succeeds, so
    the note rides along with the genuine answer rather than blocking it —
    an unrecognized SECOND fragment should never stop the FIRST, valid one
    from being applied.
    """
    unmatched = _cpq_engine.detect_unmatched_change_targets(question, attrs, matched_vns)
    if unmatched:
        phrases = ", ".join(f'"{u}"' for u in unmatched)
        result["answer"] += (
            f"\n\n*(I didn't recognize {phrases} as anything in this "
            f"configuration — did you mean something else?)*"
        )
    return result


def _scan_and_enqueue_remaining_targets(
    session: Any,
    question: str,
    attrs: list,
    *,
    exclude_vns: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Scan utterance for all valueless change targets; enqueue all but active.

    Returns (enqueued_vns, overflow_vns). The first target in appearance
    order that is NOT in exclude is treated as "active" (caller handles it);
    the rest go on pending_intent_queue.
    """
    exclude = set(exclude_vns or set())
    all_targets = _cpq_engine.detect_all_change_targets_without_value(
        question, attrs, session.filled,
        filled_multi=session.filled_multi,
        exclude_vns=exclude,
        cap=INTENT_QUEUE_CAP + 5,  # detect a few past cap so overflow is visible
    )
    remaining = [a.variable_name for a in all_targets if a.variable_name not in exclude]
    # If caller already has an active target excluded, remaining is the queue.
    # If not, first is active (caller handles) and rest are queued.
    overflow = enqueue_intent_targets(
        session, remaining, exclude=exclude, cap=INTENT_QUEUE_CAP,
    )
    enqueued = [v for v in remaining if v in session.pending_intent_queue]
    return enqueued, overflow


def _queue_followup_note(session: Any, attrs: list) -> str:
    """Human note listing queued targets still to ask."""
    if not session.pending_intent_queue:
        note = ""
    else:
        by_vn = {a.variable_name: a for a in attrs}
        labels = [
            _cpq_engine.disambiguated_label(by_vn[v], attrs)
            if v in by_vn else v
            for v in session.pending_intent_queue
        ]
        if len(labels) == 1:
            note = f"\n\n*(I'll also ask about **{labels[0]}** next.)*"
        else:
            joined = ", ".join(f"**{lbl}**" for lbl in labels)
            note = f"\n\n*(I'll ask about each next: {joined}.)*"
    if session.pending_intent_overflow:
        note += "\n\n" + format_queue_overflow_notice(
            list(session.pending_intent_overflow), attrs,
        )
        session.pending_intent_overflow = []
    return note


def _apply_intent_conservation(
    result: dict[str, Any] | None,
    question: str,
    detected_targets: set[str] | list[str],
    handled_vns: set[str] | list[str],
    session: Any,
    attrs: list,
    *,
    clarified_vns: set[str] | list[str] | None = None,
) -> dict[str, Any] | None:
    """Run intent-conservation audit; append dropped-intent notice to answer."""
    if result is None:
        return None
    audit = audit_intent_conservation(
        question, detected_targets, handled_vns, session,
        clarified_vns=clarified_vns,
        run_id=getattr(session, "run_id", "") or "",
        turn=int(getattr(session, "turn", 0) or 0),
        log=True,
    )
    if audit.dropped:
        notice = format_dropped_intent_notice(audit.dropped, attrs)
        if notice:
            result["answer"] = (result.get("answer") or "") + "\n\n" + notice
        # Refresh session_data after any queue mutations
        result["session_data"] = session.to_dict()
        tools = list(result.get("tools_called") or [])
        tools.append("cpq_intent_dropped()")
        result["tools_called"] = tools
    return result


def _build_no_value_response(
    req: "AskRequest",
    session: Any,
    attrs: list,
    target_attr: Any,
    con_rules: list,
    bml_eval: Any,
    tool_name: str,
) -> dict[str, Any]:
    """"Which value would you like for X?" follow-up for a change-verb
    naming an already-filled attribute with no resolvable new value.

    Shared by two callers (2026-07-28 refactor): the regex-based
    `detect_change_target_without_value` and the LLM change-intent
    fallback's own empty-value case ("change the hardware type" correctly
    identifies hWVersion_astro but states no new value) — previously the
    LLM path had no equivalent and silently discarded a correctly-
    identified target instead of asking, the same class of gap
    `detect_change_target_without_value` already closed for its own regex
    matches.

    Also scans the utterance for additional named targets and enqueues
    them on pending_intent_queue so multi-target "change A, B and C"
    asks each in sequence.
    """
    # Enqueue every OTHER named no-value target in this utterance.
    enqueued, _overflow = _scan_and_enqueue_remaining_targets(
        session, req.question, attrs,
        exclude_vns={target_attr.variable_name},
    )
    # Active target is not "queued" — it's pending_change_no_value.
    clear_queue_vn(session, target_attr.variable_name)

    constrained = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval)
    options_block = _cpq_engine.next_question_prompt(
        target_attr, constrained_item_values=constrained.get(target_attr.entity_id),
    )
    current_val = session.filled.get(target_attr.variable_name)
    current_note = (
        f"\n\n*Currently set to: **"
        f"{session.display_filled.get(target_attr.variable_name, current_val)}***"
        if current_val else ""
    )
    answer = (
        f"Which value would you like for "
        f"**{_cpq_engine.disambiguated_label(target_attr, attrs)}**?"
        f"\n\n{options_block}{current_note}"
    )
    answer += _queue_followup_note(session, attrs)
    session.pending_change_no_value_vn = target_attr.variable_name
    detected = {target_attr.variable_name} | set(enqueued) | set(
        session.pending_intent_queue or [],
    )
    # Also count overflow as detected for conservation (must not silently drop)
    if _overflow:
        detected |= set(_overflow)
    result = _append_unmatched_targets_note(
        {
            "answer": answer, "terms": [target_attr.variable_name],
            "tools_called": [f"{tool_name}({target_attr.variable_name})"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        },
        req.question, attrs, {target_attr.variable_name},
    )
    result = _apply_intent_conservation(
        result, req.question, detected,
        handled_vns=set(),  # none applied yet
        session=session, attrs=attrs,
        clarified_vns={target_attr.variable_name},
    )
    _persist_cpq_history(req.workspace_id, req.question, result["answer"])
    return result


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §10 (QA issue #2):
# no decline detector existed anywhere on the pending "which value?" path —
# "I don't want to change product" fell straight into apply_answer as an
# attempted (and failed) Product value. Stemmed with \w* on the verb forms
# (change/changing/changed) rather than one literal, learning directly from
# the earlier clarify-decline regex missing "wanted" vs "want" (§6) —
# deliberately does NOT match bare "no" alone, since that's a legitimate
# value for yes/no-shaped attrs.
_CHANGE_VALUE_DECLINE_RE = re.compile(
    r"don'?t\s+want\w*|do\s+not\s+want\w*"
    r"|no\s+chang\w*|not\s+chang\w*"
    r"|leave\s+it|keep\s+it"
    r"|never\s*mind"
    r"|cancel\s+(this|that|it)"
    r"|skip\s+(this|that)",
    re.IGNORECASE,
)


def _is_change_value_decline(reply: str) -> bool:
    return bool(_CHANGE_VALUE_DECLINE_RE.search(reply or ""))


# Thin wrappers — pure logic lives in aryx.cpq.replacement_clause so offline
# regression / unit tests can load it without FastAPI. Ask-api keeps the
# historical private names for call sites and monkeypatches.
# PROMPT 6: returns (wanted, rejected); contrast-first reversed forms.
def _extract_replacement_clause(text: str) -> tuple[str | None, str | None]:
    """See ``aryx.cpq.replacement_clause.extract_replacement_clause``."""
    return extract_replacement_clause(text)


def _remember_attr_scope(
    session: Any,
    attr: Any,
    constrained_item_values: list[str] | None,
    origin_question: str = "",
) -> None:
    """Persist the option list we just showed (PROMPT 7)."""
    if attr is None or not getattr(attr, "options", None):
        return
    cands = candidates_from_attr_options(attr.options, constrained_item_values)
    if not cands:
        return
    vn = getattr(attr, "variable_name", "") or ""
    kind = (
        "product_options"
        if "productselection" in vn.lower().replace("_", "")
        or vn.lower() == "productselectionproduct_all"
        else "attr_options"
    )
    set_pending_scope(
        session,
        kind=kind,
        candidates=cands,
        origin_question=origin_question,
        attr_vn=vn,
        asked_turn=getattr(session, "turn", 0),
    )


def _scoped_reask_response(
    req: "AskRequest",
    session: Any,
    reply: str,
    *,
    scope_label: str = "",
    tools_called: str = "cpq_scope_reask()",
) -> dict[str, Any]:
    """Build a scoped 'did you mean' / numbered re-ask; retain scope."""
    cands = list(session.pending_scope_candidates or [])
    res = resolve_against_scope(reply, cands)
    session.pending_scope_misses = int(session.pending_scope_misses or 0) + 1
    log_scope_retained(
        run_id=getattr(session, "run_id", "") or "",
        reply=reply,
        kind=session.pending_scope_kind or "",
        n_candidates=len(cands),
        suggestions=res.suggestions,
        misses=session.pending_scope_misses,
    )
    numbered = session.pending_scope_misses >= scope_loop_exit_threshold()
    sug = res.suggestions or cands[:3]
    if numbered:
        sug = cands  # full same-scope list, never catalog-wide
    answer = format_did_you_mean(
        reply, sug, numbered=numbered, scope_label=scope_label,
    )
    _persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": [tools_called],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _constrain_excluding_rejected(
    attr: Any,
    rejected_text: str | None,
    base_constrained: list[str] | None,
) -> list[str] | None:
    """Drop the option matching ``rejected_text`` from the allowed set.

    Option-level rejection (not VN-level): ``session.negated_vns`` tracks
    *attributes* suppressed by "exclude any X", while a replacement rejects
    a *value* on the target attr. Constrained-values is the correct path.
    """
    if not rejected_text or not getattr(attr, "options", None):
        return base_constrained
    rej = _cpq_engine.apply_answer(attr, rejected_text)
    if not rej:
        return base_constrained
    excluded_iv = rej[0]
    base = (
        list(base_constrained)
        if base_constrained is not None
        else [o.item_value for o in attr.options]
    )
    filtered = [v for v in base if v != excluded_iv]
    # Never return an empty allow-list — that would force match failure even
    # for the wanted value if option inventory was unexpected.
    if not filtered:
        return base_constrained
    return filtered


def _handle_cascade(
    req: "AskRequest",
    session: Any,
    attrs: list,
    changed_attr: Any,
    new_value_hint: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    constrained_item_values: list[str] | None = None,
) -> dict[str, Any]:
    """STEP 6 — Cascade: apply a change, invalidate dependents, re-run rule loop."""
    push_snapshot(session, reason="cascade")
    clear_clarify(session, getattr(changed_attr, "variable_name", None))
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
    # set_type=="2" attrs are transient UI/action-layer fields, always
    # excluded from the final payload (build_payload's own unconditional
    # rule) — they never re-enter `filled`/`pending_variables` after this
    # rerun either, so naming them here as "needing fresh values" is
    # misleading (live-verified: "Include a Spare Battery with each body
    # camera" was announced as recalculating, then silently never
    # reappeared anywhere — correct outcome, confusing wording).
    dependent_labels = [
        _cpq_engine.disambiguated_label(by_eid[eid], attrs) for eid in dependent_eids
        if eid in by_eid and by_eid[eid].set_type != "2"
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

    # Replacement extraction: only the WANTED value reaches apply_answer.
    # Rejected option is excluded via constrained_item_values so fuzzy match
    # cannot re-pick it even if residual text leaks through.
    wanted_clause, rejected_clause = _extract_replacement_clause(new_value_hint)
    apply_hint = wanted_clause if wanted_clause else new_value_hint
    apply_constrained = _constrain_excluding_rejected(
        changed_attr, rejected_clause, constrained_item_values,
    )
    if wanted_clause or rejected_clause:
        logger.info(
            "cpq_replacement: attr=%s wanted=%r rejected=%r apply_hint=%r "
            "constrained_excl=%s",
            getattr(changed_attr, "variable_name", None),
            wanted_clause, rejected_clause, apply_hint,
            apply_constrained is not None and apply_constrained != constrained_item_values,
        )

    # Lock in the new value for the changed attr
    if changed_attr.select_type == "multi":
        # UNION every mentioned option with the current selection — a
        # post-completion "include Locking Molle Mount" ADDS a row, it
        # doesn't wipe rows already chosen (and a previously DECLINED
        # empty grid simply becomes the new rows). apply_multi_answer
        # extracts all named options, not just the best single match.
        # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — the
        # constrained set must reach the multi-select matcher too, not just
        # the single-select apply_answer path below. PROMPT 6: apply_hint
        # is wanted-only; apply_constrained excludes rejected option.
        mentioned = _cpq_engine.apply_multi_answer(
            changed_attr, apply_hint, apply_constrained,
        )
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
        result = _cpq_engine.apply_answer(
            changed_attr, apply_hint, apply_constrained,
        )
        if result:
            session.filled[changed_attr.variable_name] = result[0]
            session.display_filled[changed_attr.variable_name] = result[1]
            session.filled_source[changed_attr.variable_name] = "user"
    if not result:
        # Could not parse new value — ask for clarification. Re-passes the
        # SAME constrained_item_values the original ask used (docs/
        # CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §10, QA issue
        # #3) — without this, a retry after a failed match fell back to
        # attr.options unfiltered (the full cross-family catalog, e.g. 328
        # legacy models) instead of the scoped list shown on the first ask.
        opts_prompt = _cpq_engine.next_question_prompt(
            changed_attr, constrained_item_values=constrained_item_values,
        )
        answer = (
            f"I couldn't match that to a valid option for "
            f"**{_cpq_engine.disambiguated_label(changed_attr, attrs)}**. "
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
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
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

    # Multi-target intent queue drain: every change-request entry point
    # converges here. Clear the just-applied attr from the queue, then
    # force the queue head to pending_variables[0] (outranks catalog /
    # hardware ordering) so the next turn asks for its value. Not excluded
    # for already being in session.filled — change targets are normally
    # already filled.
    clear_queue_vn(session, changed_attr.variable_name)
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)

    # D1, docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md: the value the customer
    # just explicitly chose is authoritative input for the REST of this
    # turn's evaluation — if the rule pass above silently reassigned it
    # (e.g. a stably-true recommendation rule targeting the same attr,
    # live-verified: Billing Option -> "Annual" silently became
    # "Immediate"), revert rather than reporting the substituted value as
    # if it were accepted. Scoped to single-select only (a multi-select's
    # own union semantics are a different question, not this bug's
    # shape). Checking the OUTCOME here catches the bug regardless of
    # which internal mechanism causes it — no changes to auto_fill/
    # apply_recommendation_rules/evaluate_rules_loop needed, and every
    # OTHER attribute's cascade above is completely unaffected.
    _user_value_overridden = (
        changed_attr.select_type != "multi" and result
        and session.filled.get(changed_attr.variable_name) != result[0]
    )
    if _user_value_overridden:
        _requested_display = result[1]
        session.filled.pop(changed_attr.variable_name, None)
        session.display_filled.pop(changed_attr.variable_name, None)
        session.filled_source.pop(changed_attr.variable_name, None)
        pending = [changed_attr] + [
            a for a in pending if a.variable_name != changed_attr.variable_name
        ]
        session.pending_variables = [a.variable_name for a in pending]

    # Build cascade notice
    # Amendment (2026-07-28), docs/CPQ_LLM_INTENT_FIRST_PLAN.md: use the
    # disambiguated label here, not the raw shared one — several attrs in
    # this catalog carry the identical display_label "Service Type", and
    # when more than one changes value in the same turn (the user's own
    # change plus an independently-firing recommendation rule elsewhere)
    # the raw label made every line read as the same fact repeated.
    _changed_label = _cpq_engine.disambiguated_label(changed_attr, attrs)
    if _user_value_overridden:
        cascade_note = (
            f"Your choice for **{_changed_label}** "
            f"(**{_requested_display}**) isn't valid given the rest of this "
            f"configuration — please choose a different value:"
        )
    else:
        changed_disp = session.display_filled.get(changed_attr.variable_name, new_value_hint)
        cascade_note = f"Updated **{_changed_label}** → **{changed_disp}**."
    if dependent_labels and not _user_value_overridden:
        # Plain-English framing, not a raw label dump — "This invalidated:
        # X, Y — re-evaluating." read as internal/mechanical shorthand
        # rather than something a sales rep could act on. Names WHY (the
        # change just made) and WHAT is happening (fresh values being
        # computed), singular/plural phrased so one dependent doesn't read
        # oddly as a list.
        if len(dependent_labels) == 1:
            cascade_note += (
                f" Because **{_changed_label}** changed, "
                f"**{dependent_labels[0]}** depends on it and needs a fresh "
                f"value — recalculating now."
            )
        else:
            dep_list = ", ".join(f"**{lbl}**" for lbl in dependent_labels)
            cascade_note += (
                f" Because **{_changed_label}** changed, these "
                f"depend on it and need fresh values: {dep_list} — "
                f"recalculating now."
            )
    for dvar, dvals in dropped_multi.items():
        dattr = next((a for a in attrs if a.variable_name == dvar), None)
        dlabel = dattr.display_label if dattr else dvar
        cascade_note += (
            f" Removed **{', '.join(dvals)}** from **{dlabel}** — "
            f"no longer valid after this change."
        )

    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    if pending:
        # New conflicts to resolve → FORMAT A (change notice + next question only)
        session.status = "configuring"
        next_attr = pending[0]
        # Queue head that is already filled still needs a value pick — set
        # pending_change_no_value so the next bare reply is captured as the
        # new value (same as _build_no_value_response).
        if (
            session.pending_intent_queue
            and next_attr.variable_name == session.pending_intent_queue[0]
            and session.filled.get(next_attr.variable_name)
        ):
            session.pending_change_no_value_vn = next_attr.variable_name
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals,
            )
            _remember_attr_scope(session, next_attr, _cvals, req.question)
        answer = cascade_note + "\n\n" + q_block
        answer += _queue_followup_note(session, attrs)
    elif unresolved_grid_gaps:
        # A selected grid option has NO resolvable quantity attr at all
        # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9) — never silently
        # complete with a permanent per-row gap; block and ask the
        # customer to resolve it (remove the selection or pick another).
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            cascade_note + "\n\n"
            f"⚠️ {gap_list} has no quantity field configured in this "
            f"catalog. Please remove it or choose a different option "
            f"before this configuration can be completed."
        )
    else:
        # All resolved → verbose summary, JSON only on request (§6/Phase K)
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
        )
        answer = (
            cascade_note + "\n\n"
            f"Configuration complete for **{session.product_name}**.\n\n"
            + (f"{summary}\n\n" if summary else "")
            + f"Click **JSON** below to see the full payload, "
              f"say **confirm** to submit, or describe any changes."
        )

    _persist_cpq_history(req.workspace_id, req.question, answer)
    result = {
        "answer": answer, "terms": [], "tools_called": ["cpq_cascade()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
    return result


def _handle_multi_select_removal(
    req: "AskRequest",
    session: Any,
    attrs: list,
    changed_attr: Any,
    to_remove: list[str],
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (removal) — deselect one or more options from an already-
    selected multi-select (e.g. "remove Jacket Magnetic Mount" after both
    Shirt and Jacket were selected).

    Also drops the removed option's own per-option quantity attr (via
    resolve_array_grid_links) — a quantity for a mount no longer selected
    is stale data, not a value worth keeping around or re-showing.
    """
    current = session.filled_multi.get(changed_attr.variable_name, [])
    remaining = [v for v in current if v not in to_remove]
    removed_display = [
        next((o.display_name for o in changed_attr.options if o.item_value == v), v)
        for v in to_remove
    ]
    session.filled_multi[changed_attr.variable_name] = remaining
    if remaining:
        session.display_filled[changed_attr.variable_name] = ", ".join(
            next((o.display_name for o in changed_attr.options if o.item_value == v), v)
            for v in remaining
        )
    else:
        # An empty selection after an explicit removal is a settled,
        # user-confirmed answer (same "(none)" convention auto_fill's own
        # decline-handling uses) — never silently re-guessed or re-asked.
        session.display_filled[changed_attr.variable_name] = "(none)"
    session.filled_source[changed_attr.variable_name] = "user"

    grid_links = _cpq_engine.resolve_array_grid_links(attrs)
    qty_map = grid_links.get(changed_attr.variable_name, {})
    dropped_qty_labels: list[str] = []
    for removed_iv in to_remove:
        qty_vn = qty_map.get(removed_iv.strip().lower())
        if qty_vn and qty_vn in session.filled:
            qty_attr = next((a for a in attrs if a.variable_name == qty_vn), None)
            dropped_qty_labels.append(
                _cpq_engine.disambiguated_label(qty_attr, attrs) if qty_attr else qty_vn
            )
            session.filled.pop(qty_vn, None)
            session.display_filled.pop(qty_vn, None)
            session.filled_source.pop(qty_vn, None)
            session.pending_variables = [v for v in session.pending_variables if v != qty_vn]

    cascade_note = (
        f"Removed **{', '.join(removed_display)}** from "
        f"**{_cpq_engine.disambiguated_label(changed_attr, attrs)}** "
        f"— now: **{session.display_filled[changed_attr.variable_name]}**."
    )
    if dropped_qty_labels:
        cascade_note += (
            f" Also cleared {', '.join(f'**{lbl}**' for lbl in dropped_qty_labels)} "
            f"— no longer needed."
        )

    # Re-run the rule loop once, same as the single-change cascade path —
    # a removal can un-invalidate a constraint or re-open an option the
    # prior selection had closed off.
    hints = _cpq_engine.extract_hints(req.question)
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)
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

    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    if pending:
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp,
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    elif unresolved_grid_gaps:
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            cascade_note + "\n\n"
            f"⚠️ {gap_list} has no quantity field configured in this "
            f"catalog. Please remove it or choose a different option "
            f"before this configuration can be completed."
        )
    else:
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_multi_select_removal()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _handle_attr_activation(
    req: "AskRequest",
    session: Any,
    attrs: list,
    activated_attr: Any,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (activation) — re-activate a real, currently-excluded,
    optional catalog attribute back into the quote (D2,
    docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md).

    Re-runs the rule loop once, same as every other change/removal
    handler (re-activating an attr can itself affect other rules, e.g. a
    constraint that was only ever evaluated against attrs visible before
    this one existed). `auto_fill`'s existing blind first-by-order
    fallback would happily guess a value for this attr the same way it
    does for any other ordinary optional attr — but the user just
    explicitly asked for THIS one, so it deserves a real question, not a
    guess (D2 §4.3 "never silently guesses"). A genuine rule-derived fill
    (filled_source == "rule"/"country_derived") is a determined value,
    not a guess, and is left alone.
    """
    activated_vn = activated_attr.variable_name

    hints = _cpq_engine.extract_hints(req.question)
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)

    if (activated_vn in filled
            and session.filled_source.get(activated_vn) not in ("rule", "country_derived")
            and activated_vn not in _grid_qty_vns):
        filled.pop(activated_vn, None)
        display_filled.pop(activated_vn, None)
        _act_attr_resolved = next(
            (a for a in visible_attrs if a.variable_name == activated_vn), None)
        if _act_attr_resolved is not None:
            pending.insert(0, _act_attr_resolved)

    # Built AFTER the override decision above — a real determined value
    # (e.g. a source="default"/"rule" fill this same pass) gets stated
    # directly rather than a misleading "what value would you like?"
    # when nothing further is actually being asked.
    _activated_label = _cpq_engine.disambiguated_label(activated_attr, attrs)
    if activated_vn in filled:
        _act_display = display_filled.get(activated_vn, filled[activated_vn])
        cascade_note = (
            f"Added **{_activated_label}** → **{_act_display}**."
        )
    else:
        cascade_note = (
            f"Added **{_activated_label}** to your quote — "
            f"what value would you like?"
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

    if pending:
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp,
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    else:
        session.status = "post_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_attr_activation()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _handle_attr_clear(
    req: "AskRequest",
    session: Any,
    attrs: list,
    cleared_attr: Any,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (nullify) — clear an optional single-select attribute's
    current value back to empty (D4, docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md).

    Sets the value to the empty-string "user"-sourced marker `auto_fill`'s
    single-select branch now respects (mirrors `filled_multi`'s existing
    empty-plus-"user" "(none)" convention) — never immediately re-guessed
    by the blind first-by-order fallback on the rule-loop pass this same
    handler triggers. `detect_attr_clear` already verified live that no
    active rule would refire for this attr before this handler is ever
    called.
    """
    vn = cleared_attr.variable_name
    prev_display = session.display_filled.get(vn, session.filled.get(vn, ""))
    session.filled[vn] = ""
    session.display_filled[vn] = "(none)"
    session.filled_source[vn] = "user"
    cascade_note = (
        f"Cleared **{_cpq_engine.disambiguated_label(cleared_attr, attrs)}** "
        f"(was **{prev_display}**)."
    )

    hints = _cpq_engine.extract_hints(req.question)
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn2, iv in catalog_hints.items():
        hints.setdefault(vn2, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn2, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn2, iv)
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)

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

    if pending:
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp,
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    else:
        session.status = "post_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_attr_clear()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _handle_bulk_quantity_change(
    req: "AskRequest",
    session: Any,
    attrs: list,
    selector_vn: str,
    item_values: list[str],
    new_qty: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (bulk quantity) — set every already-selected row's quantity
    attr for one grid selector to the same value in one turn (e.g. "change
    both the mounting types quantity to 67").
    """
    grid_links = _cpq_engine.resolve_array_grid_links(attrs)
    item_map = grid_links.get(selector_vn, {})
    by_vn = {a.variable_name: a for a in attrs}
    selector_attr = by_vn.get(selector_vn)
    updated_labels: list[str] = []
    _seen_qty_vns: set[str] = set()
    for item_value in item_values:
        qty_vn = item_map.get(item_value.strip().lower())
        # resolve_array_grid_links' substring heuristic can map two
        # distinct options (e.g. "MOLLE Mount" and "Locking Molle Mount")
        # to the SAME quantity attr — set it once, not once per option, so
        # the cascade note doesn't list the same attr twice.
        if not qty_vn or qty_vn in _seen_qty_vns:
            continue
        _seen_qty_vns.add(qty_vn)
        qty_attr = by_vn.get(qty_vn)
        session.filled[qty_vn] = new_qty
        session.display_filled[qty_vn] = new_qty
        session.filled_source[qty_vn] = "user"
        updated_labels.append(qty_attr.display_label if qty_attr else qty_vn)

    selector_label = selector_attr.display_label if selector_attr else selector_vn
    cascade_note = (
        f"Set {', '.join(f'**{lbl}**' for lbl in updated_labels)} to **{new_qty}**."
        if updated_labels else
        f"Couldn't find a quantity field for the selected **{selector_label}** options."
    )

    hints = _cpq_engine.extract_hints(req.question)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    session.negated_vns = sorted(set(session.negated_vns))
    negated_vns = set(session.negated_vns)

    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
    _grid_qty_vns = {a.variable_name for a in pending}
    for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
        visible_attrs, filled, session.filled_multi):
        if _qty_attr.variable_name not in _grid_qty_vns:
            pending.append(_qty_attr)
            _grid_qty_vns.add(_qty_attr.variable_name)
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

    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    if pending:
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp,
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    elif unresolved_grid_gaps:
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            cascade_note + "\n\n"
            f"⚠️ {gap_list} has no quantity field configured in this "
            f"catalog. Please remove it or choose a different option "
            f"before this configuration can be completed."
        )
    else:
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_bulk_quantity_change()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _handle_cascade_multi(
    req: "AskRequest",
    session: Any,
    attrs: list,
    matches: list,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> "dict[str, Any] | None":
    """STEP 6 (multi) — apply every change a single message names at once
    (up to `detect_change_requests_multi`'s cap), union their cascade
    dependents, then re-run the rule loop ONCE — not once per change, or a
    dependent could get re-derived against a stale intermediate state
    between two changes applied in the same turn.

    Product decision: partial apply. Whichever of the named changes parse
    (a real value found for that attr) are applied; any that don't are
    reported by label, not silently dropped and not rejecting the whole
    turn. Returns None (caller falls through to the normal "didn't catch
    that" nudge) only when NONE of the named changes could be applied —
    mirrors `detect_change_request` returning None today.
    """
    push_snapshot(session, reason="cascade_multi")
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
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    applied_notes: list[str] = []
    failed_labels: list[str] = []
    all_dependent_eids: set[int] = set()
    changed_vns: set[str] = set()
    # D1, docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md: single-select applies
    # are checked against the outcome AFTER the rule pass below (a
    # recommendation rule could silently reassign one) — their notes are
    # built then, not immediately, so a reverted one gets the honest
    # "isn't valid" wording instead of "Updated". Multi-select applies
    # aren't subject to this check (different, union-based semantics —
    # same scope boundary as the single-change path).
    _user_requested_single: dict[str, tuple[Any, str, str]] = {}

    for changed_attr, new_value_hint in matches:
        if changed_attr.variable_name in changed_vns:
            continue  # same attr matched twice in one message — apply once

        dependent_eids = _cpq_engine.find_cascade_dependents(
            changed_attr, attrs, hiding_rules, rec_rules, con_rules,
        )
        # Strip this attr + its dependents from filled before re-applying —
        # same as the single-change path (_handle_cascade).
        session.filled.pop(changed_attr.variable_name, None)
        session.display_filled.pop(changed_attr.variable_name, None)
        session.filled_source.pop(changed_attr.variable_name, None)
        for eid in dependent_eids:
            a = by_eid.get(eid)
            if a:
                session.filled.pop(a.variable_name, None)
                session.display_filled.pop(a.variable_name, None)
                session.filled_source.pop(a.variable_name, None)

        if changed_attr.select_type == "multi":
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
            # Ask, don't report: queue unparsable targets so we solicit a
            # value on the next turn instead of dead-ending in failed_labels.
            failed_labels.append(changed_attr.display_label)
            enqueue_intent_targets(
                session, [changed_attr.variable_name], cap=INTENT_QUEUE_CAP,
            )
            continue

        changed_vns.add(changed_attr.variable_name)
        clear_queue_vn(session, changed_attr.variable_name)
        all_dependent_eids |= set(dependent_eids)
        if changed_attr.select_type == "multi":
            changed_disp = session.display_filled.get(changed_attr.variable_name, new_value_hint)
            applied_notes.append(
                f"Updated **{_cpq_engine.disambiguated_label(changed_attr, attrs)}** "
                f"→ **{changed_disp}**."
            )
        else:
            # Note built after the rule pass below, once we know whether
            # this value actually stuck (D1).
            _user_requested_single[changed_attr.variable_name] = (
                changed_attr, result[0], result[1],
            )

    if not changed_vns and not session.pending_intent_queue:
        # None of the named changes could be applied at all — let the
        # caller fall through to the normal "didn't catch that" nudge,
        # same as detect_change_request returning None.
        return None
    if not changed_vns and session.pending_intent_queue:
        # All targets lacked parseable values — ask the first queued one.
        head_vn = session.pending_intent_queue[0]
        head_attr = next((a for a in attrs if a.variable_name == head_vn), None)
        if head_attr is not None:
            bml_eval_nv = _cpq_engine.build_bml_evaluator(
                req.workspace_id, attrs[0].catalog_prefix if attrs else "",
            )
            return _build_no_value_response(
                req, session, attrs, head_attr, con_rules, bml_eval_nv,
                "cpq_cascade_multi_queue_ask",
            )
        return None

    # set_type=="2" attrs never re-enter filled/pending after this rerun
    # and are always excluded from the final payload — see _handle_cascade's
    # identical filter for the live-verified finding this addresses.
    dependent_labels = [
        _cpq_engine.disambiguated_label(by_eid[eid], attrs) for eid in all_dependent_eids
        if eid in by_eid and by_eid[eid].variable_name not in changed_vns
        and by_eid[eid].set_type != "2"
    ]

    # Re-run full rule evaluation loop ONCE with every change applied.
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    _, _, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
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
                "rule": "cascade" if var in changed_vns else "cascade-dependent",
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

    # D1, docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md: check every single-select
    # change against the outcome — revert any the rule pass silently
    # reassigned, in the order the message named them, so each gets the
    # honest "isn't valid" wording and is re-asked instead of reported as
    # accepted. See _handle_cascade's identical check for the full
    # rationale (same live-verified bug: a stably-true recommendation
    # rule reasserting its own value over the customer's explicit choice).
    _overridden_attrs: list[Any] = []
    for _vn, (_attr, _want_value, _want_display) in _user_requested_single.items():
        _attr_label = _cpq_engine.disambiguated_label(_attr, attrs)
        if session.filled.get(_vn) == _want_value:
            changed_disp = session.display_filled.get(_vn, _want_display)
            applied_notes.append(f"Updated **{_attr_label}** → **{changed_disp}**.")
        else:
            session.filled.pop(_vn, None)
            session.display_filled.pop(_vn, None)
            session.filled_source.pop(_vn, None)
            _overridden_attrs.append(_attr)
            applied_notes.append(
                f"Your choice for **{_attr_label}** (**{_want_display}**) "
                f"isn't valid given the rest of this configuration — please "
                f"choose a different value."
            )
    if _overridden_attrs:
        pending = _overridden_attrs + [
            a for a in pending
            if a.variable_name not in {a2.variable_name for a2 in _overridden_attrs}
        ]
        session.pending_variables = [a.variable_name for a in pending]

    # Build the combined cascade notice — one line per applied change,
    # then one combined "these depend on what changed" note (same
    # plain-English framing as the single-change path).
    cascade_note = " ".join(applied_notes)
    if failed_labels:
        # Queued for sequential asks — never dead-end as "left unchanged".
        cascade_note += (
            f" I'll ask about each next"
            f" ({', '.join(f'**{lbl}**' for lbl in failed_labels)})."
        )
    # Drain queue head to front of pending (same convergence as single cascade).
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)
    if dependent_labels:
        if len(dependent_labels) == 1:
            cascade_note += (
                f" Because those changed, **{dependent_labels[0]}** depends "
                f"on them and needs a fresh value — recalculating now."
            )
        else:
            dep_list = ", ".join(f"**{lbl}**" for lbl in dependent_labels)
            cascade_note += (
                f" Because those changed, these depend on them and need "
                f"fresh values: {dep_list} — recalculating now."
            )
    for dvar, dvals in dropped_multi.items():
        dattr = next((a for a in attrs if a.variable_name == dvar), None)
        dlabel = dattr.display_label if dattr else dvar
        cascade_note += (
            f" Removed **{', '.join(dvals)}** from **{dlabel}** — "
            f"no longer valid after this change."
        )

    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    if pending:
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp,
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    elif unresolved_grid_gaps:
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            cascade_note + "\n\n"
            f"⚠️ {gap_list} has no quantity field configured in this "
            f"catalog. Please remove it or choose a different option "
            f"before this configuration can be completed."
        )
    else:
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_cascade_multi()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


_LLM_INTENT_ATTRS_CAP_HARD = 500  # safety bound on relevance-scoring work, not a relevance cutoff
_LLM_INTENT_RELEVANT_CAP = 10
_WORD_RE = re.compile(r"[a-z0-9]+")


def _relevant_intent_candidates(
    question: str, candidates: list, fallback_to_full: bool = True,
) -> list:
    """Narrow the candidate list to the attrs the question is actually
    plausibly about, by simple word overlap against display_label and
    option display names.

    Live-verified need (2026-07-22): handing the full ~40-attr candidate
    list to the classifier — even one restricted to filled attrs — diluted
    the signal enough that a phrase the model correctly classified in
    isolation came back "none" once real catalog noise was mixed in.
    Keeping only the attrs whose own vocabulary overlaps the question
    keeps the prompt small and on-topic; falls back to the full (capped)
    list only when nothing overlaps at all, so an unanticipated phrasing
    still gets a chance rather than being silently starved to zero attrs.

    fallback_to_full=False (Amendment 17, docs/CPQ_UNIFIED_INTENT_
    CLASSIFIER_PLAN.md): a caller gating whether to make an LLM call at
    all — not just narrowing an already-decided candidate list — needs
    "nothing genuinely overlaps" to mean an empty result, not the full
    list; the default behavior would make that gate fire on every turn.

    Scored by rarity-weighted overlap, not a raw overlap COUNT
    (2026-07-28 fix) — live-verified gap: "change the hardware type"
    against a real 153-filled-attr session scored Hardware Version
    (unique word "hardware") EQUAL to a dozen other "...Type"-suffixed
    attrs (Order Type, Band Class Type, Service Type, etc., all sharing
    the generic word "type") — with 10+ ties and a hard cap of 10, the
    actual match got crowded out before the LLM ever saw it. Each
    matched word now contributes 1/(how many candidates' own vocab
    contains that word) instead of a flat 1 — a word only ONE attr owns
    (like "hardware") scores far higher than one a dozen attrs share
    (like "type"), so a genuinely distinctive match wins over generic
    vocabulary noise regardless of how many attrs happen to share it.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    if not q_words:
        return candidates[:_LLM_INTENT_RELEVANT_CAP] if fallback_to_full else []
    vocabs = []
    for a in candidates:
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocabs.append(vocab)
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for a, vocab in zip(candidates, vocabs):
        overlap_words = q_words & vocab
        if overlap_words:
            score = sum(1.0 / doc_freq[w] for w in overlap_words)
            scored.append((score, a))
    if not scored:
        return candidates[:_LLM_INTENT_RELEVANT_CAP] if fallback_to_full else []
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [a for _score, a in scored[:_LLM_INTENT_RELEVANT_CAP]]


def _llm_resolve_pending_answer(
    question: str, pending_attr: Any, workspace_id: int,
) -> dict[str, Any] | None:
    """LLM fallback for STEP 5's pending-answer path (Amendment 2 Gap A,
    docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md), tried only after
    apply_answer's fragment/word-boundary matching finds nothing.

    Live-confirmed need (2026-07-26): a long, natural, multi-intent
    sentence bundling the product name together with subscription type,
    quantity, and package tier never fragment-matches any of a long
    option list, even though a human reads the intended option
    immediately. Scoped to ONLY the one pending attr's own real options —
    never the full session or raw JSON — same never-guess discipline as
    every other Tier-2 fallback in this file: a returned value outside the
    attr's real option list is discarded, never trusted.

    Confidence-gated (decided 2026-07-24): a sentence can be genuinely
    ambiguous between two real, valid options in the same list — that's a
    judgment error, not hallucination, and scoping alone can't catch it.
    The prompt asks for a confidence signal alongside its pick; low
    confidence returns the narrowed candidate list instead of the pick
    itself, so the caller shows those for the customer to confirm rather
    than silently committing to a guess between two valid options.

    Returns {"iv": item_value, "disp": display_name, "confidence": "high"}
    on a confident, validated pick; {"confidence": "low", "candidates":
    [display_name, ...]} when the model itself signals low confidence;
    None on any failure (no options, LLM error, invented value, etc).

    Includes each option's internal item_value alongside its display_name
    (Amendment 7 follow-up, decided 2026-07-26): some catalogs' real
    option text is a marketing alias with no textual resemblance to what
    a customer actually says (confirmed live — CommandCentral Aware
    2024's own Product option displays as "Direct Streaming", the
    item_value is "COMMANDCENTRAL AWARE2"). Showing only display_name
    made a plainly-answerable sentence unresolvable in principle, not
    just in practice — the model had no path to the right answer at all.
    Matching either field is accepted; item_value is never itself shown
    to the customer, only used to widen what the model can recognize.
    """
    if not pending_attr.options:
        return None
    opt_lines = "\n".join(
        f"- {o.display_name} (internal code: {o.item_value})"
        if o.item_value.lower() != o.display_name.lower() else f"- {o.display_name}"
        for o in pending_attr.options[:200]
    )
    sys = (
        "You extract which option a user's message names for a single "
        "pending question, even when the message is a long sentence "
        "bundling several unrelated details together. Some options show "
        "an internal code in parentheses — the customer may say something "
        "closer to that code than to the display name (e.g. a product's "
        "internal/marketing name). Only pick from the OPTIONS list given "
        "— never invent one. If the message could plausibly mean two or "
        "more of the real options, set confidence to low and list the "
        "ones it could be; only set confidence to high when exactly one "
        "option is clearly named."
    )
    user = (
        f"QUESTION BEING ANSWERED: {pending_attr.display_label}\n\n"
        f"OPTIONS:\n{opt_lines}\n\n"
        f"USER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"value": "<exact display name from the list, or empty>", '
        '"confidence": "high"|"low", '
        '"candidates": ["<display name>", ...] (only when confidence is low)}'
    )
    valid_by_lower = {o.display_name.lower(): o for o in pending_attr.options}

    def _validate(parsed: dict) -> dict[str, Any] | None:
        confidence = parsed.get("confidence")
        if confidence == "low":
            raw_candidates = parsed.get("candidates") or []
            candidates = [c for c in raw_candidates if isinstance(c, str) and c.lower() in valid_by_lower]
            if len(candidates) < 2:
                return None
            return {"confidence": "low", "candidates": candidates}
        value = parsed.get("value") or ""
        opt = valid_by_lower.get(value.lower())
        if confidence != "high" or opt is None:
            return None
        return {"confidence": "high", "iv": opt.item_value, "disp": opt.display_name}

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)


def _llm_classify_intent_core(
    sys_prompt: str, user_prompt: str, workspace_id: int,
    validate: Any,
) -> Any:
    """Shared skeleton for every Tier-2 LLM intent fallback in this file.

    Factored out of `_llm_classify_change_intent` and
    `_llm_resolve_label_collision` (both pre-existing, both already
    following this exact shape): call the menial-tier model, parse its
    JSON reply, and hand the parsed dict to a caller-supplied `validate`
    function that enforces the never-guess discipline specific to that
    call site (only real attrs/options ever get trusted). Any exception —
    LLM call failure, malformed JSON, missing braces — returns None rather
    than raising, since every caller here is a fallback that must never
    crash the turn.
    """
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys_prompt, user_prompt, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        logger.debug("llm intent core: llm call or parse failed: %r", exc)
        return None
    return validate(parsed)


def _llm_classify_is_cpq_question(
    question: str, workspace_id: int, prior_context: str = "",
) -> bool:
    """Amendment 16 Layer 1 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    Tier-2 intent gate. Two call sites with structurally different needs:

    1. `run_ask`'s fresh-turn router — deciding whether to enter CPQ mode
       at all, before any CPQ session/context exists. No `prior_context`
       is passed here; this classification is, and must stay, the raw
       sentence alone.
    2. `_synthesise`'s mid-session Q&A scope check — deciding whether an
       in-flight follow-up question is still in scope. Live-confirmed gap
       (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §14): "what
       is the error" right after the CPQ engine's own gate error was
       wrongly refused as out-of-scope, because classified alone it reads
       as an unrelated tech-support question — the one fact that would
       make it recognizably relevant (the prior turn WAS an error) was
       never shown to the classifier. `prior_context` (the recent
       conversation, already computed by the caller) fixes this for call
       site 2 without changing call site 1's behavior at all.

    Deliberately biased toward "quote" on anything but a confident "no":
    live-confirmed twice this session (a missing regex plural, an
    alias-fallback that only checked internal BOM codes) that a false
    "no" here means a genuine CPQ request silently exits to the generic
    LLM pipeline with no error — bypassing this engine's entire
    "never guess" discipline. A false "yes" costs only Step 1's own
    anchor-prompting asking a clarifying question, the same as any
    ordinary first turn. An LLM-call failure (exception, malformed JSON)
    is NOT covered by that bias — it returns False, the same default this
    turn already had before this gate existed, since a failed call
    provides no information at all, positive or negative.
    """
    sys = (
        "You classify whether a customer's message is asking to "
        "configure, quote, or order a product — a CPQ/configuration "
        "request — versus a general question or something unrelated. "
        "Bias toward \"quote\" whenever the message plausibly could be "
        "about ordering or configuring something, even if phrased "
        "unusually or missing an obvious trigger word; only classify as "
        "\"not_quote\" when you are confident it is NOT that at all."
    )
    context_block = (
        f"\nRECENT CONVERSATION (for context only — classify the MESSAGE "
        f"below, but consider whether it plausibly follows up on this):\n"
        f"{prior_context}\n"
        if prior_context.strip() else ""
    )
    user = (
        f"{context_block}MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"classification": "quote"|"not_quote"}'
    )

    def _validate(parsed: dict) -> bool | None:
        classification = parsed.get("classification")
        if classification not in ("quote", "not_quote"):
            return None
        return classification == "quote"

    return _llm_classify_intent_core(sys, user, workspace_id, _validate) is True


def _llm_classify_is_ask_in_scope(
    question: str, workspace_id: int, prior_context: str = "",
) -> bool:
    """Scope gate for the general Ask synthesis path (`_synthesise`'s
    call site only — NOT the CPQ-routing call site in `run_ask`, which
    must keep using `_llm_classify_is_cpq_question`'s narrower,
    quote-biased judgment).

    `_llm_classify_is_cpq_question` was previously reused here, but that
    function only ever answers "is this an order/configure/quote
    request?" — confirmed live this caused the Ask feature to refuse
    almost every question, including legitimate lookups against tracked
    data (e.g. "what are the entities present in suppliers?"), because
    most real questions aren't literally quote/order requests and so
    correctly got `not_quote` from that classifier, which this call site
    then wrongly treated as "off-topic."

    This classifier answers the broader, actually-relevant question for
    Ask: is this about product configuration/quoting OR the enterprise/
    catalog data this system tracks at all? Only a question genuinely
    unrelated to that domain (small talk, an unrelated topic) should
    classify as out of scope.

    `prior_context` (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md
    §14, ported from `_llm_classify_is_cpq_question` onto this broader
    classifier since this — not that one — is the call site that gates
    general Ask): the recent conversation, when the caller has it, so a
    mid-session follow-up like "what is the error" can be recognized as
    in-scope when the prior turn was the engine's own gate error, rather
    than classified alone as an unrelated tech-support question.

    Fails OPEN, not closed: `_llm_classify_intent_core` returns `None` on
    a malformed reply or an LLM-call exception, same as every other
    caller of that shared skeleton. Collapsing that `None` into `False`
    (as an earlier version of this function did via `is True`) recreates
    the exact bug this function exists to fix — a classification
    failure would silently withhold valid graph facts and reproduce the
    blanket "outside what I track" refusal, indistinguishable from a
    genuine out-of-scope question. Only an explicit `out_of_scope`
    result should count as out of scope; a failed or unparseable call
    provides no information at all and must not be treated as evidence
    either way, so it's treated as in-scope.
    """
    sys = (
        "You classify whether a customer's message is in scope for a "
        "product-configuration and enterprise-data assistant — meaning "
        "it asks about product configuration, quoting/ordering, OR the "
        "catalog/enterprise data this system tracks (entities, "
        "attributes, relationships, records) in any way. "
        "Bias toward \"in_scope\" whenever the message plausibly could be "
        "asking about tracked data or product configuration, even if "
        "phrased as a general question rather than a quote request; only "
        "classify as \"out_of_scope\" when you are confident it is about "
        "something else entirely (e.g. small talk, an unrelated topic)."
    )
    context_block = (
        f"\nRECENT CONVERSATION (for context only — classify the MESSAGE "
        f"below, but consider whether it plausibly follows up on this):\n"
        f"{prior_context}\n"
        if prior_context.strip() else ""
    )
    user = (
        f"{context_block}MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"classification": "in_scope"|"out_of_scope"}'
    )

    def _validate(parsed: dict) -> bool | None:
        classification = parsed.get("classification")
        if classification not in ("in_scope", "out_of_scope"):
            return None
        return classification == "in_scope"

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate)
    return result is not False


def _llm_extract_multi_attr_hints(
    question: str, candidates: list, workspace_id: int,
) -> dict[str, str]:
    """Amendment 17 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): map a
    single dense, multi-fact sentence to several still-unresolved attrs at
    once, instead of asking for each one individually.

    Live-motivating scenario: "...standard subscription for 25 devices at
    25 locations...package of 'Plus'...new solution type" — Tier-1's
    extract_catalog_hints deliberately leaves this unresolved for two
    separate, correct reasons (see engine.py's own docstring): (1) it
    never guesses when the same value ("25") is valid for two sibling
    attrs (devices vs. locations) — it can't use word ADJACENCY to tell
    them apart, only per-attr option membership; (2) single-word values
    ("Plus", "New") fall below its minimum-trust bar. Both are correct,
    safe defaults for a regex — but leave a human-obvious multi-fact
    sentence to be asked back one attr at a time.

    Scoped to ONLY the candidates the caller already determined are
    plausibly mentioned (via `_relevant_intent_candidates(...,
    fallback_to_full=False)`) — never the full pending list, and the
    caller never invokes this at all when fewer than 2 candidates
    genuinely overlap the question, so this never fires on an ordinary
    short reply.

    Same never-guess discipline as every other Tier-2 fallback here: a
    returned variable_name must be one of the given candidates; a
    returned value must be a real option for THAT SPECIFIC attr (checked
    per-attr, not globally — the same collision `extract_catalog_hints`
    itself refuses to resolve must not be waved through here just because
    an LLM is involved). Only "high" confidence mappings are kept — a
    "low" confidence mapping is dropped silently, leaving that one attr
    pending and asked normally next, exactly as if this function had
    never run for it; this function only ever adds resolved facts, it
    never blocks or re-asks anything the caller was already going to do.

    A candidate with no fixed option list (free-text/numeric, e.g.
    Amendment 12's device-count shape) has its stated value trusted as
    typed — the same trust a normal user-typed reply to that same pending
    question already gets elsewhere in this engine; this catalog's own
    `apply_validation_rules` is the real safety net for those, unchanged.

    Returns {variable_name: item_value} for every validated, high-
    confidence mapping (possibly empty; never raises).
    """
    by_vn = {a.variable_name: a for a in candidates}
    attr_lines = []
    for a in candidates:
        opts = ", ".join(
            f"{o.display_name} (code: {o.item_value})"
            if o.item_value.lower() != o.display_name.lower() else o.display_name
            for o in a.options[:40]
        ) if a.options else "(free text/number — no fixed option list)"
        attr_lines.append(f"- {a.variable_name} — \"{a.display_label}\": {opts}")
    sys = (
        "You extract answers to SEVERAL still-open configuration questions "
        "from one customer sentence that may bundle multiple facts "
        "together (e.g. a quantity, a tier, a plan type, all in one "
        "sentence). For each attribute below, decide whether the sentence "
        "clearly states its value. Use word adjacency to tell apart "
        "attributes that could share the same raw value (e.g. \"25 "
        "devices\" vs \"25 locations\" — the number alone doesn't say "
        "which attribute it answers, the nearby word does). Only map an "
        "attribute when its value is unambiguous; when the same number or "
        "word plausibly applies to more than one attribute here, or the "
        "sentence doesn't mention an attribute at all, leave it out "
        "entirely — do not guess, and never invent a value outside the "
        "options given for that attribute."
    )
    user = (
        "STILL-OPEN ATTRIBUTES:\n" + "\n".join(attr_lines) + "\n\n"
        f"CUSTOMER SENTENCE: {question}\n\n"
        'Reply ONLY as JSON: {"mappings": [{"variable_name": "<exact name '
        'from the list>", "value": "<exact option display name or code, '
        'or the stated number/text for a free-text attribute>", '
        '"confidence": "high"|"low"}, ...]} — omit any attribute you are '
        "not confident about rather than including it with low confidence."
    )

    def _validate(parsed: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in (parsed.get("mappings") or []):
            if not isinstance(m, dict) or m.get("confidence") != "high":
                continue
            attr = by_vn.get(m.get("variable_name"))
            if attr is None:
                continue
            val = str(m.get("value") or "").strip()
            if not val:
                continue
            if attr.options:
                match = next(
                    (o for o in attr.options
                     if o.display_name.lower() == val.lower()
                     or o.item_value.lower() == val.lower()),
                    None,
                )
                if match is None:
                    continue
                result[attr.variable_name] = match.item_value
            else:
                result[attr.variable_name] = val
        return result

    return _llm_classify_intent_core(sys, user, workspace_id, _validate) or {}


def _label_collision_for(attr: Any, attrs: list, session: Any = None) -> list | None:
    """Detect a shared display_label collision for a SYSTEM-initiated next
    question (the engine's own auto-selected `pending[0]`), not a
    user-typed query — `detect_label_collision` (engine.py) only fires
    against an explicit user question naming the label, so it never runs
    for the ordinary "what do we ask next" step.

    Live-confirmed gap (2026-07-26): a genuine same-catalog collision
    (`ConnectorTypeProductArray_swSoln` and `productSelectionProduct_all`
    both labeled "Product") was silently resolved to whichever attr came
    first in catalog order — the engine asked "Product" and backed it
    with the WRONG attr's options (113 unrelated values instead of the
    real 325-option Product list), with no disambiguation at all. This
    almost certainly explains earlier session reports of a persistent,
    wrong 113-option "Product" prompt that survived even after the
    cross-catalog scoping fix (Amendment 4) — a different bug entirely.

    Excludes candidates already resolved (in `session.filled` or
    `session.filled_multi`) when `session` is given — live-confirmed
    follow-up bug (2026-07-26): once ONE of two same-labeled attrs was
    answered, the remaining unresolved one still got treated as an
    unresolved "collision", re-presenting the same "which one did you
    mean?" choice even though there was no longer anything ambiguous —
    only one candidate was actually still in play. Once filtering leaves
    fewer than 2 truly-unresolved candidates, there's nothing left to
    disambiguate.

    Returns the full list of same-labeled, still-unresolved attrs (2+)
    when `attr`'s label collides with others, else None.
    """
    matches = [a for a in attrs if a.display_label == attr.display_label]
    if session is not None:
        matches = [
            a for a in matches
            if a.variable_name not in session.filled
            and a.variable_name not in session.filled_multi
        ]
    if len({a.variable_name for a in matches}) >= 2:
        return matches
    return None


def _compose_disambiguation_question(
    question: str, prompt_topic: str, candidate_labels: list[str],
    already_known: dict[str, str], static_fallback: str, workspace_id: int,
) -> str:
    """Amendment 16 Layer 2 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    compose a natural clarifying question instead of a flat numbered-list
    template, for the three ambiguous moments this doc scopes it to (label
    collision, model-leaf list, low-confidence pending-answer).

    NEVER invents an option — `candidate_labels` are the exact,
    already-validated real candidates the caller determined; the LLM only
    phrases the question naturally and reflects back `already_known` facts
    (country, product, ...) so the customer isn't asked to repeat something
    already said. Composing phrasing is lower-stakes than Gap A's
    value-picking (`_llm_resolve_pending_answer`) — it never commits to an
    answer, only asks a question — so unlike Gap A there's no separate
    confidence gate here; the safety net is the fallback below instead.

    Falls back to `static_fallback` (today's exact template) verbatim
    whenever: the LLM call raises, the response is empty, OR the composed
    text is missing any real candidate's identifying text (checked via the
    same alphanumeric-only normalization used elsewhere in this file) —
    a composed question that silently dropped an option would be worse
    than today's plain list, so that case must never be trusted. Behavior
    is never worse than before this existed.
    """
    if not candidate_labels:
        return static_fallback
    known_lines = "\n".join(f"- {k}: {v}" for k, v in already_known.items() if v)
    sys = (
        "You write ONE short, natural, conversational clarifying question "
        "for a customer configuring a product, given what they already "
        "said and a fixed list of real options they must choose between. "
        "Reflect back anything already known so they aren't asked to "
        "repeat it. List the exact options given, formatted naturally — "
        "never add, remove, rename, or invent an option. Reply with ONLY "
        "the question text (the option list may be part of it) — no JSON, "
        "no preamble, no explanation of what you're doing."
    )
    user = (
        f"CUSTOMER'S MOST RECENT MESSAGE: {question}\n\n"
        f"ALREADY KNOWN:\n{known_lines or '(nothing yet)'}\n\n"
        f"WHAT TO ASK ABOUT: {prompt_topic}\n\n"
        "REAL OPTIONS (use exactly these, do not invent others):\n"
        + "\n".join(f"- {c}" for c in candidate_labels)
    )
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        text = text.strip()
        if not text:
            return static_fallback
        norm_text = re.sub(r"[^a-z0-9]", "", text.lower())
        for label in candidate_labels:
            norm_label = re.sub(r"[^a-z0-9]", "", label.lower())
            if norm_label and norm_label not in norm_text:
                return static_fallback  # a real candidate got dropped — never trust this
        return text
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        logger.debug("disambiguation composer failed: %r", exc)
        return static_fallback


def _label_collision_prompt(
    collision: list, session: Any,
    question: str = "", workspace_id: int = 1,
) -> str:
    """Render the disambiguation prompt for a label collision — composed
    conversationally via the LLM (Amendment 16 Layer 2) when possible,
    falling back to the original flat template otherwise. `question`/
    `workspace_id` default to values that make the fallback path behave
    identically to before Layer 2 existed, for any caller not yet updated
    to pass them."""
    lines = "\n".join(
        f"- **{a.variable_name}**"
        f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
        for a in collision
    )
    static_fallback = (
        f"There are {len(collision)} different attributes labeled "
        f"**\"{collision[0].display_label}\"** in this catalog — which one "
        f"did you mean?\n\n{lines}"
    )
    if not question:
        return static_fallback
    return _compose_disambiguation_question(
        question, f'which attribute they mean by "{collision[0].display_label}"',
        [a.variable_name for a in collision],
        {"Country": getattr(session, "country", ""),
         "Product": getattr(session, "product_name", "")},
        static_fallback, workspace_id,
    )


def _narrow_label_collision(question: str, collision: list) -> list:
    """Narrow a label-collision candidate list by relevance to the question
    before presenting it (Amendment 2 Gap B, docs/CPQ_UNIFIED_INTENT_
    CLASSIFIER_PLAN.md) — reuses `_relevant_intent_candidates`'s existing,
    already-generic word-overlap scoring instead of a new per-catalog
    heuristic. Live-confirmed need (2026-07-26): a genuine same-catalog
    "Solution Type" collision (RAorderType_swSoln / serviceType_swSoln /
    package_swSoln) presented all 3 unconditionally even when the
    customer's own phrasing ("new solution type") already overlaps only
    one of them.

    Returns the narrowed list (only the top-scoring candidates) when the
    question's vocabulary overlaps at least one candidate's label/options;
    returns the original, unnarrowed list when nothing overlaps at all —
    never narrows to zero, never guesses among a genuine tie.

    Live-confirmed regression (2026-07-26): an early version of this
    function narrowed all the way to a SINGLE candidate on a long,
    multi-intent sentence whose generic words happened to coincidentally
    overlap just one candidate's option text (e.g. "standard"/"plus"
    appearing among that one attr's own option values), silently
    eliminating 2 otherwise-equally-plausible candidates without ever
    asking the user — an auto-resolve this plan explicitly deferred
    pending more testing (see Amendment 2 Gap B). Fixed: (1) the shared
    display_label's own words are excluded from scoring — every candidate
    here has the IDENTICAL label by construction, so label words can never
    discriminate between them and only add coincidental noise; (2)
    narrowing that would collapse to fewer than 2 candidates is rejected
    and the original, unnarrowed list is returned instead — narrowing the
    shown list is safe (it still asks), auto-resolving to one is not.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    if not q_words:
        return collision
    shared_label_words = set(_WORD_RE.findall(collision[0].display_label.lower()))
    scored = []
    for a in collision:
        vocab = set()
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocab -= shared_label_words
        overlap = len(q_words & vocab)
        scored.append((overlap, a))
    top_score = max(score for score, _a in scored)
    if top_score == 0:
        return collision
    narrowed = [a for score, a in scored if score == top_score]
    if len(narrowed) < 2:
        return collision
    return narrowed


def _llm_classify_change_intent(
    question: str, attrs: list, session: Any, workspace_id: int,
) -> "tuple[dict[str, str] | None, int, int]":
    """LLM fallback for remove/change intent, tried only after every regex
    detector (detect_multi_select_removal, detect_change_request(s_multi))
    found nothing. Reuses the existing menial-tier model already wired for
    term extraction (`_extract_terms`) — no new model config. Classify-only:
    it never synthesizes prose, only picks {intent, variable_name, value}.

    Same never-guess discipline as the regex path: any attribute name the
    model returns that isn't one of the attrs actually present in the
    current session is discarded. Live-verified finding (2026-07-22): two
    real attrs in this catalog share the display_label "Mounting Type"
    (mountType_viSoln, single, vs. mountingTypeArray_viSoln, multi) — the
    label alone isn't enough to disambiguate, so the prompt keys on
    variable_name + select_type + the attr's real option list, and the
    returned value is re-validated against that specific attr's own
    options before being trusted (a "remove" against a single-select attr,
    or a value not in the target attr's option set, is discarded).
    """
    filled_candidates = [
        a for a in attrs
        if a.variable_name in session.filled or a.variable_name in session.filled_multi
    ]
    if not filled_candidates:
        return None, 0, 0
    # Relevance-score BEFORE capping — a catalog with dozens of filled
    # attrs (promotions, accessories, etc.) can push the actually-relevant
    # attr past a fixed positional cap if capped by catalog order first.
    # Live-verified bug (2026-07-22): capping to the first 40 filled attrs
    # by catalog order cut mountingTypeArray_viSoln out entirely before
    # relevance scoring ever saw it, because dozens of unrelated
    # promotion/accessory attrs came first in attrs' catalog order.
    candidates = _relevant_intent_candidates(
        question, filled_candidates[:_LLM_INTENT_ATTRS_CAP_HARD])
    by_vn = {a.variable_name: a for a in candidates}
    catalog_lines = []
    for a in candidates:
        current = session.filled_multi.get(a.variable_name) or session.filled.get(a.variable_name)
        opts = ", ".join(o.display_name for o in a.options[:15]) if a.options else "(free text)"
        catalog_lines.append(
            f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
            f"current={current!r}; options=[{opts}]"
        )
    sys = (
        "You classify a user's message about an in-progress product configuration. "
        "Decide if they want to REMOVE an already-selected option from a [multi] "
        "attribute, or CHANGE a [single] attribute's value. Attributes can share the "
        "same display label but are different fields — pick by variable_name, "
        "select_type, and which one's current value or options actually match what "
        "the user is talking about. Only use attribute names from the list given — "
        "never invent one. If neither intent clearly applies, or you're unsure which "
        "of two similarly-labeled attrs is meant, say none."
    )
    user = (
        "ATTRIBUTES (variable_name [select_type] (label): current=...; options=[...]):\n"
        + "\n".join(catalog_lines) +
        f"\n\nUSER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"intent": "remove"|"change"|"none", '
        '"variable_name": "<exact name from list, or empty>", '
        '"value": "<option text or new value, or empty>"}'
    )
    def _validate(parsed: dict) -> dict[str, str] | None:
        intent = parsed.get("intent")
        vn = parsed.get("variable_name") or ""
        value = parsed.get("value") or ""
        if intent not in ("remove", "change") or not vn:
            return None
        # "remove" genuinely needs a value (which option to remove) — but
        # "change" with an empty value is a real, distinct outcome (the
        # attribute WAS identified, just with no new value stated), not a
        # failed classification — the caller routes it to a "which value
        # would you like?" follow-up instead of discarding the match
        # entirely (2026-07-28 fix, live-verified: "change the hardware
        # type" correctly named hWVersion_astro with value="", previously
        # thrown away here).
        if intent == "remove" and not value:
            return None
        attr = by_vn.get(vn)
        if attr is None:
            logger.debug("llm intent fallback: model named vn %r not in candidates %r",
                          vn, list(by_vn))
            return None
        if intent == "remove" and attr.select_type != "multi":
            logger.debug("llm intent fallback: rejected remove on non-multi attr %r", vn)
            return None
        if value and attr.options:
            valid_values = {o.display_name.lower() for o in attr.options} | {
                o.item_value.lower() for o in attr.options
            }
            if value.lower() not in valid_values:
                logger.debug("llm intent fallback: value %r not a real option for %r", value, vn)
                return None
        return {"intent": intent, "variable_name": vn, "value": value}

    # Inlines _llm_classify_intent_core's call+parse shape rather than
    # reusing it directly (2026-07-28): that shared helper's other 4 call
    # sites return a bare bool/dict and never attach token usage to a
    # user-visible response, so changing its signature to a 3-tuple would
    # force pointless unpacking on all of them. This is the one caller
    # whose result DOES reach a response with hardcoded "cpq-engine, 0
    # tokens" usage (via the "change" + empty-value branch below) — same
    # live-confirmed gap _llm_classify_intent_universal already fixed for
    # the Phase 2 path.
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        logger.debug("llm intent fallback: llm call or parse failed: %r", exc)
        return None, 0, 0
    return _validate(parsed), _it, _ot


# ── Phase 1, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md — shadow-mode ──────
# universal intent classifier. NOT wired into any actual dispatch decision:
# called read-only, its result only ever reaches a log line, exactly like
# the Fix 4 `count_turn_intents` diagnostic this mirrors. See
# _shadow_classify_cpq_turn's docstring for the call site and guarantee.

_INTENT_CATEGORY_LIST = ", ".join(c.value for c in IntentCategory)


def _llm_classify_intent_universal(
    question: str, attrs: list, session: Any, workspace_id: int,
) -> "tuple[IntentResult | None, int, int]":
    """One structured classification call per the Phase 0 schema
    (`aryx.cpq.intent_schema`).

    Returns (result, prompt_tokens, completion_tokens) — 2026-07-28: token
    counts are threaded through so callers that actually DISPATCH on this
    classification (unlike Phase 1's shadow-mode logging, which only ever
    reads `result`) can report real usage instead of the hardcoded
    "cpq-engine, 0 tokens" every deterministic handler's response carries.
    Live-confirmed UX gap: the LLM-first path was correctly classifying
    and dispatching, but its response still showed 0 tokens/"cpq-engine",
    making it indistinguishable from the pure deterministic path even
    though a real LLM call drove the decision.

    Reuses `_relevant_intent_candidates` (the existing pre-filter every
    other `_llm_*` fallback in this file already relies on) to keep the
    candidate list on-topic and bounded even against an 800+-attr catalog
    (plan doc mitigation #6) — never the full attrs list unfiltered.

    The LLM is never asked for a `variable_name`/`item_value` — only a
    plain-language `target_description`/`new_value_description` per the
    schema's own two-layer design; resolving that description to a real
    catalog attr is `_resolve_target_description`'s job, not this
    function's. Fails closed (returns None) on any LLM/parse error, same
    discipline as every other Tier-2 fallback here.

    Two fixes (2026-07-28) for a live-confirmed hallucination in shadow-
    mode data: fed the bare reply "serviceType_astro" (answering a PRIOR
    turn's label-collision question), the classifier invented a plausible-
    sounding but nonexistent attribute ("Service Category") instead of
    recognizing the literal reply.

    1. Every pending-state tracker CpqSession carries — not just
       `pending_variables[0]` — is surfaced to the prompt: a bare reply
       almost always answers ONE of these, never a fresh, freestanding
       request, and the model had no way to know that with only one line
       of context.
    2. The prompt now explicitly tells the model to check the message
       against the CANDIDATES' OWN variable_name fields first when it
       looks like a raw identifier (snake/camelCase, no spaces) rather
       than natural language, and to prefer `ambiguous`/low confidence
       over inventing a plausible-sounding label when nothing matches
       literally — the same "never guess a real decision" discipline the
       deterministic detectors already follow.
    """
    candidates = _relevant_intent_candidates(question, attrs)
    catalog_lines = []
    for a in candidates:
        current = session.filled_multi.get(a.variable_name) or session.filled.get(a.variable_name)
        opts = ", ".join(o.display_name for o in a.options[:15]) if a.options else "(free text)"
        catalog_lines.append(
            f"- \"{a.display_label}\" [{a.select_type}] (variable_name={a.variable_name}): "
            f"current={current!r}; options=[{opts}]"
        )
    by_vn = {a.variable_name: a for a in attrs}

    def _pending_desc(vn: str) -> str:
        a = by_vn.get(vn)
        return f"{a.display_label} (variable_name={vn})" if a else vn

    pending_lines: list[str] = []
    if session.pending_variables:
        pending_lines.append(
            f"- The system just asked about: {_pending_desc(session.pending_variables[0])}. "
            "A short/bare reply is almost certainly answering THIS."
        )
    if session.pending_change_collision_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_change_collision_vns)
        pending_lines.append(
            f"- The system just asked WHICH of these identically-labeled "
            f"attributes was meant: {_opts}. A reply naming one of these "
            "variable_names or an index number is answering THIS, not "
            "requesting a change to something else."
        )
    if session.pending_change_no_value_vn:
        pending_lines.append(
            f"- The system just asked what NEW VALUE to set for: "
            f"{_pending_desc(session.pending_change_no_value_vn)}. A short "
            "reply is almost certainly that value, not a fresh request."
        )
    if session.pending_clarify_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_clarify_vns)
        pending_lines.append(
            f"- The system just asked WHICH attribute was meant by a vague "
            f"request ({session.pending_clarify_question!r}): {_opts}. "
            "A short reply naming one of these labels, variable_names, or a "
            "list index is answering THAT clarify — not a fresh lookup."
        )
    if session.pending_label_collision_vns:
        _opts = ", ".join(_pending_desc(v) for v in session.pending_label_collision_vns)
        pending_lines.append(
            f"- The system just asked which of these identically-labeled "
            f"attributes a QUESTION was about: {_opts}."
        )
    pending_block = (
        "PENDING STATE — what the system just asked, before this message:\n"
        + "\n".join(pending_lines) + "\n\n"
        if pending_lines else ""
    )
    sys = (
        "You classify a user's message in an in-progress product configuration "
        "chatbot. Reply ONLY as JSON matching this exact schema (no other text):\n"
        + json.dumps(INTENT_RESULT_JSON_SCHEMA, indent=1) + "\n\n"
        f"Valid category values: {_INTENT_CATEGORY_LIST}.\n"
        "NEVER invent or guess a catalog identifier — target_description and "
        "new_value_description are PLAIN LANGUAGE descriptions of what the user "
        "means, never a raw field code. If you cannot confidently name a single "
        "clear target, or the message could plausibly mean 2+ different fields "
        "in the list below, use category=\"ambiguous\" and give a specific "
        "clarifying_question — never guess between plausible options.\n\n"
        "If the message itself looks like a raw identifier — snake_case or "
        "camelCase, no spaces, not a phrase a person would naturally type — "
        "check it against the candidates' own variable_name values FIRST "
        "(shown in parentheses below) before attempting any description. "
        "Never invent a plausible-sounding attribute name to explain an "
        "identifier you don't recognize; if it doesn't match any listed "
        "variable_name and there's no PENDING STATE explaining it, use "
        "confidence=\"low\" and category=\"ambiguous\" instead."
    )
    user = (
        f"{pending_block}"
        "ATTRIBUTES CURRENTLY RELEVANT (label [type] (variable_name=...): "
        "current=...; options=[...]):\n"
        + "\n".join(catalog_lines) +
        f"\n\nUSER MESSAGE: {question}"
    )
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — shadow call must never crash the turn
        logger.debug("cpq_shadow_intent: llm call or parse failed: %r", exc)
        return None, 0, 0
    return parse_intent_result(parsed), _it, _ot


def _resolve_target_description(
    description: str, attrs: list,
) -> "tuple[ConfigAttr | None, list[ConfigAttr]]":
    """Resolve a plain-language target_description to a real catalog attr —
    the deterministic "exactness" layer the LLM-first design (plan doc §5)
    relies on.

    NOT built on `_relevant_intent_candidates` — live-confirmed bug during
    Phase 2 validation: that function returns the top-K (K=10) candidates
    by score, not just the tied-best ones, so it almost always returns
    2+ candidates whenever ANY word overlaps at all (its actual job —
    narrowing an LLM prompt's candidate list — never needed a single
    winner). Reusing it here made every resolution attempt look
    "ambiguous" even for an attr with a genuinely unique label. This
    scores every attr directly against display_label + option display
    names and only resolves when there is a single STRICTLY-highest-
    scoring attr with a nonzero score — a tie at the top, or zero
    overlap, both mean "unresolved."

    Scoring is rarity-weighted (1/document_frequency per matched word,
    same fix applied to `_relevant_intent_candidates` for the identical
    bug): live-confirmed during Phase 2 validation that raw overlap
    COUNT ties a distinctive word ("solution") together with a generic
    word shared by dozens of attrs' labels/options ("type"), so e.g.
    "Solution Type" (which should uniquely score highest against
    `solutionTypeDevices_astro`, matching BOTH words) instead tied with
    ~50 unrelated Type-suffixed attrs that only matched "type" — because
    a raw count of 1 look identical to another count of 1 regardless of
    how common the matched word is catalog-wide. Rarity weighting makes
    a match on a rare word worth far more than a match on a word present
    in every third attr's option list.

    Returns (resolved_attr, all_candidates_with_nonzero_overlap).
    `resolved_attr` is None whenever resolution didn't narrow to exactly
    one clear winner — logged/handled as unresolved by the caller, never
    silently guessed at (plan doc mitigation #1/#4: this is precisely
    where a hallucinated-but-plausible target must be caught, not passed
    through).
    """
    d_words = set(_WORD_RE.findall(description.lower()))
    if not d_words:
        return None, []
    vocabs = []
    for a in attrs:
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        for o in a.options:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        vocabs.append(vocab)
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for a, vocab in zip(attrs, vocabs):
        overlap_words = d_words & vocab
        if overlap_words:
            score = sum(1.0 / doc_freq[w] for w in overlap_words)
            scored.append((score, a))
    if not scored:
        return None, []
    scored.sort(key=lambda pair: pair[0], reverse=True)
    candidates = [a for _score, a in scored]
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][1], candidates
    return None, candidates


def _shadow_classify_cpq_turn(
    req: "AskRequest", session: Any, attrs: list,
) -> None:
    """Phase 1 shadow-mode hook — docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

    Called once per turn, read-only: classifies + resolves via the new
    universal-intent path and logs the outcome, but NEVER returns anything
    to the caller, NEVER mutates `session`, and is wrapped in a bare
    try/except so any failure here is invisible to the actual turn — same
    guarantee `count_turn_intents` (Fix 4) already established for its own
    diagnostic. The REAL dispatch decision continues to come entirely from
    the existing deterministic detectors, unchanged.

    Correlated with the real turn's outcome by run_id: `run_ask` logs the
    actual `tools_called`/category right after `_run_cpq_turn` returns,
    tagged with the same `session.run_id` this logs — comparing the two
    log lines (grep by run_id) is the "log agreement/disagreement" Phase 1
    calls for, without needing an in-process diff against a function with
    dozens of early-return call sites.
    """
    try:
        result, _it, _ot = _llm_classify_intent_universal(
            req.question, attrs, session, req.workspace_id)
        if result is None:
            logger.info(
                "cpq_shadow_intent: message %r -> classification failed/unparseable",
                req.question,
            )
            return
        resolved_summary = []
        for t in ([result.target] if result.target else result.targets):
            attr, candidates = _resolve_target_description(t.target_description, attrs)
            resolved_summary.append({
                "target_description": t.target_description,
                "resolved_vn": attr.variable_name if attr else None,
                "candidate_count": len(candidates),
            })
        logger.info(
            "cpq_shadow_intent: message %r -> category=%s confidence=%s "
            "resolved=%s clarifying_question=%r rationale=%r",
            req.question, result.category.value, result.confidence.value,
            resolved_summary, result.clarifying_question, result.rationale,
        )
    except Exception:  # noqa: BLE001 — shadow diagnostic must never affect the turn
        logger.debug("cpq_shadow_intent: diagnostic failed", exc_info=True)


def _gateway_to_intent_result(
    gw: Any,
    attrs: list,
    value_display: str | None,
) -> IntentResult | None:
    """Map a quarantined GatewayIntentResult onto IntentResult for dispatch.

    Uses candidate-resolved variable_name → display_label and value_ref →
    display_name (passed in as value_display). Never trusts free-text
    item_value from the model. Returns None for categories the existing
    _dispatch_intent_result does not yet handle (fall through).
    """
    from aryx.cpq.intent_schema import GatewayIntentResult as _GIR
    if not isinstance(gw, _GIR):
        return None
    by_vn = {a.variable_name: a for a in attrs}
    target = None
    if gw.variable_name and gw.variable_name in by_vn:
        attr = by_vn[gw.variable_name]
        target = ChangeTarget(
            target_description=attr.display_label,
            new_value_description=value_display,
        )
    # Prefer gateway-selected display_label so _resolve_target_description
    # can exact-match; if no target and category needs one, refuse map.
    needs_target = gw.intent_category in {
        IntentCategory.CHANGE_REQUEST,
        IntentCategory.CHANGE_TARGET_WITHOUT_VALUE,
        IntentCategory.CHANGE_REQUESTS_MULTI,
    }
    if needs_target and target is None:
        return None
    return IntentResult(
        category=gw.intent_category,
        confidence=gw.confidence,
        target=target,
        targets=[target] if (
            gw.intent_category == IntentCategory.CHANGE_REQUESTS_MULTI
            and target is not None
        ) else [],
        clarifying_question=gw.clarifying_question,
        rationale=gw.rationale,
    )


def _with_classify_usage(
    result_dict: "dict[str, Any] | None", prompt_tokens: int, completion_tokens: int,
) -> "dict[str, Any] | None":
    """Adds the LLM-first classification call's real token usage into an
    already-built response dict, and relabels the model fields so the UI
    can tell this response was actually driven by an LLM call (2026-07-28)
    — see `_dispatch_intent_result`'s docstring. A no-op when result_dict
    is None (a delegated handler can itself return None in principle) or
    when there's nothing to add (prompt_tokens == completion_tokens == 0,
    e.g. classification hit the durable/in-memory cache path with no
    fresh call).
    """
    if result_dict is None or (not prompt_tokens and not completion_tokens):
        return result_dict
    usage = result_dict.get("usage") or {}
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + prompt_tokens
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + completion_tokens
    usage["menial_model"] = "cpq-llm-first"
    result_dict["usage"] = usage
    return result_dict


def _dispatch_intent_result(
    req: "AskRequest", session: Any, attrs: list, result: IntentResult,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int = 0, classify_completion_tokens: int = 0,
) -> "dict[str, Any] | None":
    """Phase 2 (PARTIAL), docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

    `classify_prompt_tokens`/`classify_completion_tokens` (2026-07-28): the
    real token usage from the classification call that produced `result` —
    added into every returned response's own "usage" dict (see
    `_with_classify_usage` below) so the UI reflects that an actual LLM
    call drove this response, instead of every handler's usual hardcoded
    "cpq-engine, 0 tokens". Live-confirmed UX gap: the LLM-first path was
    dispatching correctly, but its response was indistinguishable from the
    pure deterministic path because the classification call's own cost was
    silently discarded rather than reported.

    Attempts to dispatch an LLM classification directly to the existing
    handler functions, bypassing the regex waterfall — returns None
    whenever it can't confidently do so, which the caller MUST treat as
    "fall through to the unchanged deterministic path," never as a
    terminal failure. This is the only contract this function has to
    honor: never mutate `session` or return a real response unless it is
    actually confident and resolved.

    Scope of this initial landing — intentionally partial, not every
    category from the Phase 0 schema:
      - CHANGE_REQUEST, CHANGE_REQUESTS_MULTI: dispatched to the SAME
        _handle_cascade/_handle_cascade_multi the regex path already
        uses. The plain-language `new_value_description` is passed
        through UNRESOLVED as the `new_value_hint` — those handlers
        already call `apply_answer`/`apply_multi_answer` internally to
        turn a hint into a real item_value and already have their own
        "couldn't match that" fallback, so there is no separate
        resolution step to duplicate here.
      - CHANGE_TARGET_WITHOUT_VALUE (2026-07-28 addition): dispatched to
        the SAME `_build_no_value_response` helper the regex-based
        `detect_change_target_without_value` and the LLM change-intent
        fallback's own empty-value case already share. Live-verified need:
        "change the hardware type" — where "hardware type" doesn't
        literally contain "version" so no regex label-match ever fires —
        is correctly classified by the universal classifier (rarity-
        weighted candidate scoring, see `_relevant_intent_candidates`)
        as CHANGE_TARGET_WITHOUT_VALUE naming hWVersion_astro; without
        this branch that correct classification was silently discarded
        and the turn fell through to the generic "I didn't quite catch
        that" nudge.
      - AMBIGUOUS: answered directly with the LLM's own
        clarifying_question — no session mutation, no config-mutating
        risk.
      - OUT_OF_SCOPE: the same plain refusal wording `_llm_classify_
        is_cpq_question`'s negative case already uses.
      - Every other category (MULTI_SELECT_REMOVAL, ATTR_ACTIVATION,
        ATTR_CLEAR, BULK_QUANTITY_CHANGE, RESPONSE_MODE_REQUEST,
        APPROVAL, ATTR_QUERY, QA_QUESTION, PRODUCT_MENTION) returns
        None — deliberately deferred rather than rushed, so the
        deterministic path keeps owning them until a follow-up lands
        each one with the same care as the ones above.

    Confidence gating: LOW always returns None (fall through) regardless
    of category — mirrors the shadow-mode logging convention and plan doc
    mitigation #9 (ambiguity threshold must default conservative).

    Target resolution (for CHANGE_REQUEST's own target ATTR, not its
    value) uses `_resolve_target_description` — 0 or 2+ candidates both
    mean "unresolved," returned as None here, never guessed (mitigation
    #1/#4).
    """
    if result.confidence == Confidence.LOW:
        return None

    if result.category == IntentCategory.AMBIGUOUS:
        if not result.clarifying_question:
            return None
        # docs/config_consistency_issues_2026-07-30.md issue 1 — an attribute
        # currently hidden for this product (e.g. modelSelectionFrequency
        # BandMsl_astro on a Single-Band order) must never be offered as a
        # disambiguation candidate, no matter how well it scores.
        _hidden_vns = _cpq_engine.apply_hiding_rules(
            attrs, session.filled, hiding_rules, bml_eval,
        )[2]
        # Persist grounded pending_clarify so the next bare reply (e.g.
        # "Hardware Version") resolves instead of falling to the nudge.
        return _set_pending_clarify_and_answer(
            req, session, attrs,
            original_question=req.question,
            clarifying_question=result.clarifying_question,
            con_rules=con_rules,
            bml_eval=bml_eval,
            prompt_tokens=classify_prompt_tokens,
            completion_tokens=classify_completion_tokens,
            tool_name="cpq_llm_first_ambiguous()",
            hidden_vns=_hidden_vns,
            hiding_rules=hiding_rules,
            rec_rules=rec_rules,
        )

    if result.category == IntentCategory.OUT_OF_SCOPE:
        answer = (
            "That's outside what I track here — product configuration and "
            "quoting. Happy to help with anything about your current quote."
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return _with_classify_usage({
            "answer": answer, "terms": [], "tools_called": ["cpq_llm_first_out_of_scope()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }, classify_prompt_tokens, classify_completion_tokens)

    if result.category == IntentCategory.CHANGE_REQUEST and result.target:
        if not result.target.new_value_description:
            return None
        attr, _candidates = _resolve_target_description(
            result.target.target_description, attrs)
        if attr is None:
            return None
        return _with_classify_usage(
            _handle_cascade(
                req, session, attrs, attr, result.target.new_value_description,
                hiding_rules, rec_rules, con_rules,
            ),
            classify_prompt_tokens, classify_completion_tokens,
        )

    if result.category == IntentCategory.CHANGE_TARGET_WITHOUT_VALUE and result.target:
        attr, _candidates = _resolve_target_description(
            result.target.target_description, attrs)
        if attr is None:
            return None
        return _with_classify_usage(
            _build_no_value_response(
                req, session, attrs, attr, con_rules, bml_eval,
                "cpq_llm_first_change_target_no_value",
            ),
            classify_prompt_tokens, classify_completion_tokens,
        )

    if result.category == IntentCategory.CHANGE_REQUESTS_MULTI and result.targets:
        matches = []
        for t in result.targets:
            if not t.new_value_description:
                continue
            attr, _candidates = _resolve_target_description(t.target_description, attrs)
            if attr is not None:
                matches.append((attr, t.new_value_description))
        if len(matches) >= 2:
            return _with_classify_usage(
                _handle_cascade_multi(
                    req, session, attrs, matches, hiding_rules, rec_rules, con_rules,
                ),
                classify_prompt_tokens, classify_completion_tokens,
            )
        return None

    return None


def _llm_resolve_label_collision(
    reply: str, candidates: list, session: Any, workspace_id: int,
) -> str | None:
    """LLM fallback for resolving a label-collision reply, tried only
    after the deterministic check (exact variable_name or 1-based list
    index) finds nothing — same gating discipline as
    `_llm_classify_change_intent` (8bc505a): deterministic first, LLM
    only for genuinely looser phrasing ("the second one," "the array
    one"), never the first resort.

    Classify-only, over a FIXED, already-known candidate list (unlike the
    general remove/change fallback, there's no attribute discovery here —
    the 2+ candidates were already produced by detect_label_collision).
    Any name the model returns that isn't one of the actual candidates is
    discarded — same never-guess discipline as every other detector in
    this file.

    Includes each candidate's CURRENT value — live-verified gap (2026-07-23):
    an earlier version omitted it, and a reply like "the one that
    currently has jacket magnetic mount" (exactly the disambiguating
    detail the original collision prompt itself displays) had no way to
    resolve correctly, since the model was never told what either
    candidate's current value even was.
    """
    catalog_lines = [
        f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
        f"current={session.filled_multi.get(a.variable_name) or session.display_filled.get(a.variable_name)!r}"
        for a in candidates
    ]
    sys = (
        "You resolve which of several similarly-labeled attributes a user "
        "meant, from their reply to a disambiguation prompt. Only use "
        "variable_names from the list given — never invent one. If the "
        "reply doesn't clearly point to exactly one, say none."
    )
    user = (
        "CANDIDATES (variable_name [select_type] (label): current=...):\n"
        + "\n".join(catalog_lines)
        + f"\n\nUSER REPLY: {reply}\n\n"
        'Reply ONLY as JSON: {"variable_name": "<exact name from list, or empty>"}'
    )
    valid_vns = {a.variable_name for a in candidates}

    def _validate(parsed: dict) -> str | None:
        vn = parsed.get("variable_name") or ""
        if vn not in valid_vns:
            logger.debug("llm label-collision fallback: model named vn %r not in candidates %r",
                          vn, valid_vns)
            return None
        return vn

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)


# ── Gateway clarify memory (pending_clarify_*) ───────────────────────────────
# Live gap: "change hardware" → clarify "Hardware Version or System Key?" →
# reply "Hardware Version" had no pending state and fell to the review nudge.

_CLARIFY_STOPWORDS = frozenset({
    "change", "set", "update", "make", "switch", "modify", "edit", "alter",
    "please", "the", "a", "an", "to", "for", "my", "our", "me", "i", "want",
    "would", "like", "can", "you", "it", "this", "that", "and", "or", "of",
    "in", "on", "with", "from", "into", "value", "field", "attribute", "attr",
    "which", "what", "one", "option", "options",
    # Copula/auxiliary verbs — as generic as "and"/"or"/"of" above, just
    # missed. Live-confirmed: "what IS the carrier being selected" let
    # "is" survive the filter and false-match every already-filled
    # attribute whose display_label happens to start with "Is " (a common
    # BM-catalog boolean-flag naming convention: "Is provisioning
    # required...", "Is Quantity of X > 0", etc.) — none of them related
    # to carrier/product at all.
    "is", "are", "was", "were", "be", "being", "been",
})
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _clear_pending_clarify(session: Any) -> None:
    session.pending_clarify_vns = []
    session.pending_clarify_question = ""
    session.pending_clarify_prompt = ""
    session.pending_clarify_asked_turn = 0
    session.pending_clarify_misses = 0


def _ground_clarify_candidates(
    question: str,
    attrs: list,
    session: Any,
    clarifying_question: str | None = None,
    hidden_vns: set[str] | None = None,
) -> list:
    """Build candidate attrs from REAL catalog labels only.

    Prefer filled attrs with word-overlap against the vague utterance;
    also accept labels that appear (validated) inside the LLM clarify text
    so examples like "Hardware Version" are kept only when they exist in
    the catalog — never free-invented names.

    hidden_vns — docs/config_consistency_issues_2026-07-30.md issue 1:
    live-confirmed bug — a change request ("add VHF... as frequency
    bands") landed on modelSelectionFrequencyBandMsl_astro, an attribute
    the catalog's own hiding rule gates OFF for Single-Band products,
    because it remained a valid word-overlap candidate right alongside
    the correct, visible modelSelectionFrequencyBands_astro in this same
    disambiguation list. An attribute currently hidden for this product
    must never be offered as something to change at all, regardless of
    how well its label/name happens to score.
    """
    by_vn: dict[str, Any] = {}
    q_words = {
        w for w in _WORD_TOKEN_RE.findall((question or "").lower())
        if w not in _CLARIFY_STOPWORDS and len(w) >= 2
    }
    cq_lower = (clarifying_question or "").lower()
    _hidden = hidden_vns or set()

    scores: dict[str, float] = {}
    for a in attrs:
        if a.variable_name in _hidden:
            continue
        is_filled = (
            a.variable_name in session.filled
            or a.variable_name in session.filled_multi
        )
        label_l = (a.display_label or "").lower()
        vn_words = set(_WORD_TOKEN_RE.findall(
            a.variable_name.lower().replace("_", " "),
        ))
        label_words = set(_WORD_TOKEN_RE.findall(label_l))
        vocab = label_words | vn_words
        overlap = len(q_words & vocab) if q_words else 0
        label_in_cq = bool(label_l) and label_l in cq_lower
        vn_in_cq = a.variable_name.lower() in cq_lower
        if overlap > 0 or label_in_cq or vn_in_cq:
            # Prefer filled for change-like clarifies; still allow unfilled
            # when the catalog label is explicitly grounded in the CQ text.
            if is_filled or label_in_cq or vn_in_cq or overlap >= 2:
                by_vn[a.variable_name] = a
                # docs/config_consistency_issues_2026-07-30.md Issue 11:
                # a label grounded in the LLM's own clarifying text is the
                # strongest possible signal — rank it above any word-count
                # match. Otherwise rank by overlap (relevance), NOT label
                # length — the old `-len(display_label)` sort let long,
                # only-incidentally-matching already-filled labels ("Is
                # provisioning required in the Motorola Solutions
                # Authorized Cloud environment?") bump genuinely relevant,
                # short-labeled attrs ("Frequency Bands", "Wireless
                # Carrier") out of the top-8 cutoff entirely.
                scores[a.variable_name] = overlap + (100 if (label_in_cq or vn_in_cq) else 0)

    # Highest relevance score first; label length only breaks ties among
    # equally-relevant candidates.
    candidates = list(by_vn.values())
    candidates.sort(
        key=lambda a: (
            -scores.get(a.variable_name, 0),
            -len(a.display_label or ""),
            a.display_label or "",
            a.variable_name,
        ),
    )
    return candidates[:8]


def _grounded_clarify_prompt(candidates: list, attrs: list) -> str:
    """Numbered catalog-label list — never LLM-invented example names."""
    if not candidates:
        return "Which field did you mean? Please name the attribute."
    lines = [
        "Which attribute did you mean? Reply with the name or the number:",
    ]
    for i, a in enumerate(candidates, start=1):
        label = _cpq_engine.disambiguated_label(a, attrs)
        lines.append(f"{i}. **{label}** (`{a.variable_name}`)")
    return "\n".join(lines)


def _llm_classify_pending_clarify_reply(
    reply: str, candidates: list, session: Any, workspace_id: int,
) -> tuple[str, str | None]:
    """LLM-first classification of a pending-clarify reply into exactly
    one of three outcomes, replacing regex-based decline detection
    (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §5.2 — a
    keyword regex missed real phrasing like "don't WANTED to select"
    during testing; an LLM classification doesn't have that brittleness).

    Only reached after the cheap deterministic tiers in
    _match_pending_clarify_reply (exact variable_name, exact label,
    1-based index, containment) already found nothing — same
    "deterministic first, LLM only for genuinely looser phrasing"
    discipline as _llm_resolve_label_collision, which this scopes
    alongside rather than replaces (that function's other 5 call sites
    are untouched — this is a separate function for this one call site
    only, since its 3-way contract differs from that function's plain
    resolve-or-nothing one).

    Returns (status, variable_name):
      - ("resolved", vn)  — reply clearly names or picks one candidate
      - ("decline", None) — reply explicitly rejects all candidates
      - ("unclear", None) — reply doesn't address the question at all
    """
    catalog_lines = [
        f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
        f"current={session.filled_multi.get(a.variable_name) or session.display_filled.get(a.variable_name)!r}"
        for a in candidates
    ]
    sys = (
        "A customer was asked to pick which of several candidate "
        "attributes they meant, from a numbered list. Classify their "
        "reply as exactly one of: "
        '"resolved" (clearly names or picks one candidate), '
        '"decline" (explicitly rejects all of them — e.g. "no", "none of '
        "these\", \"that's not what I meant\", even with loose/incorrect "
        'grammar), or "unclear" (doesn\'t address the question at all — '
        "a totally unrelated new request). Only use variable_names from "
        "the list given — never invent one."
    )
    user = (
        "CANDIDATES (variable_name [select_type] (label): current=...):\n"
        + "\n".join(catalog_lines)
        + f"\n\nUSER REPLY: {reply}\n\n"
        'Reply ONLY as JSON: {"status": "resolved"|"decline"|"unclear", '
        '"variable_name": "<exact name from list, or empty>"}'
    )
    valid_vns = {a.variable_name for a in candidates}

    def _validate(parsed: dict) -> tuple[str, str | None] | None:
        status = parsed.get("status")
        if status not in ("resolved", "decline", "unclear"):
            return None
        if status == "resolved":
            vn = parsed.get("variable_name") or ""
            if vn not in valid_vns:
                logger.debug(
                    "llm pending-clarify classify: model named vn %r not "
                    "in candidates %r", vn, valid_vns,
                )
                return ("unclear", None)
            return ("resolved", vn)
        return (status, None)

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate)
    return result if result is not None else ("unclear", None)


def _reply_matches_attr_option(reply: str, attr: Any) -> bool:
    """True if `reply` exactly names one of `attr`'s real catalog values.

    docs/config_consistency_issues_2026-07-30.md issue 4 — a bare value
    reply to a "which attribute did you mean?" clarify (e.g. "VHF") often
    isn't unique across candidates (VHF is a legal option on 4 different
    frequency-band-ish attrs in the APX NEXT catalog), so this alone
    can't resolve the ambiguity — it's a building block for the
    anchor-based tie-break below, not a standalone matcher.
    """
    r = (reply or "").strip().lower()
    if not r:
        return False
    for o in (attr.options or []):
        if r == (o.item_value or "").lower() or r == (o.display_name or "").lower():
            return True
    return False


def _match_pending_clarify_reply(
    reply: str,
    candidates: list,
    session: Any,
    workspace_id: int,
) -> tuple[str, str | None]:
    """Resolve a bare reply against the pending-clarify candidate list.

    Returns (status, variable_name) — see
    _llm_classify_pending_clarify_reply's docstring for the 3-way
    contract; the deterministic tiers below only ever return "resolved"
    or defer to that function for "decline"/"unclear".
    """
    r = (reply or "").strip()
    if not r or not candidates:
        return ("unclear", None)
    r_lower = r.lower().strip(" .,:;!?\"'")
    by_vn = {a.variable_name: a for a in candidates}

    # Exact variable_name
    if r in by_vn:
        return ("resolved", r)
    for vn, a in by_vn.items():
        if vn.lower() == r_lower:
            return ("resolved", vn)

    # Exact display label (case-insensitive)
    for a in candidates:
        if (a.display_label or "").lower() == r_lower:
            return ("resolved", a.variable_name)

    # 1-based index
    if r.isdigit():
        idx = int(r) - 1
        if 0 <= idx < len(candidates):
            return ("resolved", candidates[idx].variable_name)

    # Label / vn containment (require uniqueness)
    hits: list[str] = []
    for a in candidates:
        label = (a.display_label or "").lower()
        vn_flat = a.variable_name.lower().replace("_", " ")
        if (
            r_lower in label
            or label in r_lower
            or r_lower in vn_flat
            or vn_flat in r_lower
        ):
            hits.append(a.variable_name)
    if len(hits) == 1:
        return ("resolved", hits[0])

    # Value-based match, anchored on the last clarify this session actually
    # resolved. docs/config_consistency_issues_2026-07-30.md issue 4 —
    # confirmed live: a bare value like "VHF" is a legal option on several
    # of these candidates at once, so an unanchored value match would still
    # be ambiguous; but once the customer already picked one of them
    # earlier (e.g. "Frequency Bands"), a later bare value that's valid for
    # THAT specific attr should resolve to it directly rather than
    # re-asking a question already answered.
    _anchor_vn = session.last_clarified_attr_vn
    if _anchor_vn and _anchor_vn in by_vn and _reply_matches_attr_option(r, by_vn[_anchor_vn]):
        return ("resolved", _anchor_vn)

    # No remembered anchor (or it doesn't apply here) — fall back to a
    # plain value match, only when it's unique across candidates. Never
    # guess when 2+ candidates share the value; that's still genuinely
    # ambiguous and must go to the LLM/re-ask below.
    value_hits = [a.variable_name for a in candidates if _reply_matches_attr_option(r, a)]
    if len(value_hits) == 1:
        return ("resolved", value_hits[0])

    # LLM-first: resolved / explicit decline / unclear.
    return _llm_classify_pending_clarify_reply(r, candidates, session, workspace_id)


def _apply_pending_clarify_resolution(
    req: "AskRequest",
    session: Any,
    attrs: list,
    resolved_vn: str,
    orig_question: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    bml_eval: Any,
) -> dict[str, Any]:
    """Replay the original vague utterance against the resolved attribute."""
    _clear_pending_clarify(session)
    clear_clarify(session, resolved_vn)
    # Remember this resolution as the anchor for a later bare-value reply
    # that's ambiguous across several candidates by itself (issue 4).
    session.last_clarified_attr_vn = resolved_vn
    session.last_clarified_turn = int(session.turn or 0)
    resolved_attr = next((a for a in attrs if a.variable_name == resolved_vn), None)
    if resolved_attr is None:
        answer = (
            f"I couldn't load the attribute `{resolved_vn}` from this catalog. "
            "Please name the field again."
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_pending_clarify_missing_attr()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Prefer applying a value if the ORIGINAL utterance had one for this attr.
    change = _cpq_engine.detect_change_request(
        orig_question, [resolved_attr], session.filled,
        filled_multi=session.filled_multi,
    )
    if change:
        _attr, value_hint = change
        return _handle_cascade(
            req, session, attrs, _attr, value_hint,
            hiding_rules, rec_rules, con_rules,
        )
    # Valueless change ("change hardware") → ask which value for the
    # now-resolved attribute (same helper as regex/LLM no-value paths).
    return _build_no_value_response(
        req, session, attrs, resolved_attr, con_rules, bml_eval,
        "cpq_pending_clarify_resolved",
    )


def _handle_pending_clarify_turn(
    req: "AskRequest",
    session: Any,
    attrs: list,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    bml_eval: Any,
) -> dict[str, Any] | None:
    """If a gateway clarify is pending, try to resolve this reply first.

    Returns a response dict when the pending path handles the turn;
    None when no pending_clarify is set (caller continues normally).
    """
    if not session.pending_clarify_vns:
        return None

    candidates = [
        a for a in attrs if a.variable_name in session.pending_clarify_vns
    ]
    # Preserve original candidate order from pending_clarify_vns
    order = {vn: i for i, vn in enumerate(session.pending_clarify_vns)}
    candidates.sort(key=lambda a: order.get(a.variable_name, 999))

    if not candidates:
        # Catalog no longer has these attrs — clear and fall through.
        _clear_pending_clarify(session)
        return None

    # docs/config_consistency_issues_2026-07-30.md Issue 11: a stale/wrong
    # candidate pool (e.g. from _ground_clarify_candidates surfacing
    # irrelevant attrs) must never force-match an unrelated, well-formed
    # follow-up request — confirmed live: "change Frequency Bands to X and
    # Wireless Carrier to Y" got silently mis-bound to "Carrier Selection"
    # purely because that WRONG attr was in the stale pool and happened to
    # share an option value, while the actually-correct wirelessCarrier_
    # astro was never even a candidate. _resolve_target_description is run
    # UNSCOPED (against every attr, not just the stale pool) as the
    # deterministic "exactness" check it already is elsewhere in this
    # file; a confident resolution to an attr OUTSIDE the stale pool means
    # this is a fresh request, not a reply to the old clarify.
    if _cpq_engine._CHANGE_VERB_RE.search(req.question) or _cpq_engine._ARROW_RE.search(req.question):
        _fresh_attr, _fresh_candidates = _resolve_target_description(req.question, attrs)
        if _fresh_attr is not None and _fresh_attr.variable_name not in session.pending_clarify_vns:
            _clear_pending_clarify(session)
            return None

    clarify_status, resolved_vn = _match_pending_clarify_reply(
        req.question, candidates, session, req.workspace_id,
    )
    if clarify_status == "resolved" and resolved_vn:
        return _apply_pending_clarify_resolution(
            req, session, attrs, resolved_vn,
            session.pending_clarify_question or req.question,
            hiding_rules, rec_rules, con_rules, bml_eval,
        )

    # Explicit decline (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_
    # ISSUE.md §5.2) — LLM-classified, not regex — never treat "no" as
    # just another failed guess. Clear the stale candidate list (which
    # may itself be wrong, e.g. a compound change+question message the
    # gateway couldn't resolve to one target) and ask a genuinely open
    # question instead of re-showing the same list a third time.
    if clarify_status == "decline":
        _clear_pending_clarify(session)
        answer = (
            "No problem — could you tell me specifically which attribute "
            "or setting you'd like to change or ask about?"
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_pending_clarify_decline()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Miss — do not mis-bind. Re-prompt; after 2 misses force numbered list.
    session.pending_clarify_misses = int(session.pending_clarify_misses or 0) + 1
    note_clarify(session, "_pending_clarify")
    if session.pending_clarify_misses >= 2 or should_force_numbered_options(
        session, "_pending_clarify",
    ):
        prompt = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_prompt = prompt
    else:
        prompt = (
            session.pending_clarify_prompt
            or _grounded_clarify_prompt(candidates, attrs)
        )
        prompt = (
            f"I still need to know which attribute you meant.\n\n{prompt}"
        )
    if should_offer_guided_mode(session):
        prompt = f"{prompt}\n\n{guided_mode_offer_message()}"
    _persist_cpq_history(req.workspace_id, req.question, prompt)
    return {
        "answer": prompt, "terms": list(session.pending_clarify_vns),
        "tools_called": ["cpq_pending_clarify_reprompt()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _llm_split_compound_change_and_question(
    question: str, workspace_id: int,
) -> tuple[str, str] | None:
    """LLM-first check: does this message combine a change request AND a
    separate question in one turn (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_
    CLARIFY_ISSUE.md §4)? If so, split into two self-contained strings so
    each can be dispatched through its OWN existing pipeline in the same
    turn — change applied first, then the question answered against the
    post-change state. Never invents catalog IDs/values; only rephrases
    the customer's own words into two standalone requests.

    Returns None when the message is NOT genuinely compound (a single
    change, a single question, or multiple changes with no separate
    question — that last case is already handled by
    CHANGE_REQUESTS_MULTI) — caller falls through to the existing
    clarify/ambiguous path unchanged, so a wrong split can never happen
    silently; it just means no split was applied.

    Only called from the gateway's "clarify" path (not every turn), and
    only after a cheap pre-check that the message contains a conjunction
    at all — so this adds no cost to the common, already-successful
    single-intent case.
    """
    sys = (
        "A customer sent a message to a product configuration assistant. "
        "Determine whether it combines TWO separate things: (1) a request "
        "to CHANGE or SET one attribute's value, and (2) a genuinely "
        "SEPARATE question asking about something else (a current value, "
        "available options, etc.) that is not part of the same change. "
        "If both are clearly present, split the message into two "
        "self-contained requests, each rephrased in the customer's own "
        "words as a complete standalone request. If the message is "
        "really just ONE thing — a single change, a single question, or "
        "multiple changes to different fields with no separate question "
        "mixed in — say it is not compound. Never invent details that "
        "weren't in the original message."
    )
    user = (
        f"MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"is_compound": true|false, '
        '"change_text": "<self-contained change request, or empty>", '
        '"question_text": "<self-contained question, or empty>"}'
    )

    def _validate(parsed: dict) -> tuple[str, str] | None:
        if not parsed.get("is_compound"):
            return None
        change_text = (parsed.get("change_text") or "").strip()
        question_text = (parsed.get("question_text") or "").strip()
        if not change_text or not question_text:
            return None
        return (change_text, question_text)

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)


def _set_pending_clarify_and_answer(
    req: "AskRequest",
    session: Any,
    attrs: list,
    original_question: str,
    clarifying_question: str | None,
    con_rules: list | None = None,
    bml_eval: Any = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tool_name: str = "cpq_intent_gateway_clarify()",
    hidden_vns: set[str] | None = None,
    hiding_rules: list | None = None,
    rec_rules: list | None = None,
) -> dict[str, Any]:
    """Persist grounded clarify state and return the clarify response."""
    candidates = _ground_clarify_candidates(
        original_question, attrs, session, clarifying_question, hidden_vns=hidden_vns,
    )
    # docs/config_consistency_issues_2026-07-30.md issue 4 — a fresh clarify
    # can re-propose an attribute the customer already resolved earlier in
    # this session (e.g. "Frequency Bands"), and the triggering utterance
    # can be a bare value ("VHF") that's ALSO legal on other candidates
    # (Frequency Band/Msl, Primary/Secondary Frequency) — genuinely
    # ambiguous on its own, confirmed live. If the remembered anchor is
    # among these candidates and the utterance is one of ITS real option
    # values, resolve straight to it instead of re-asking a question
    # already answered. Requires rule context (con_rules) to actually
    # apply the change; without it there's nothing to replay against yet.
    _anchor_vn = session.last_clarified_attr_vn
    if (
        _anchor_vn
        and con_rules is not None
        and hiding_rules is not None
        and rec_rules is not None
    ):
        _anchor_attr = next(
            (a for a in candidates if a.variable_name == _anchor_vn), None,
        )
        if _anchor_attr is not None and _reply_matches_attr_option(
            original_question, _anchor_attr,
        ):
            return _apply_pending_clarify_resolution(
                req, session, attrs, _anchor_vn, original_question,
                hiding_rules, rec_rules, con_rules, bml_eval,
            )
    # Single grounded candidate → skip the extra question; ask for value.
    if len(candidates) == 1 and con_rules is not None:
        _clear_pending_clarify(session)
        return _with_classify_usage(
            _build_no_value_response(
                req, session, attrs, candidates[0], con_rules, bml_eval,
                f"{tool_name}->single_candidate",
            ),
            prompt_tokens, completion_tokens,
        )

    if len(candidates) >= 2:
        session.pending_clarify_vns = [a.variable_name for a in candidates]
        session.pending_clarify_question = original_question
        session.pending_clarify_prompt = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_asked_turn = int(session.turn or 0)
        session.pending_clarify_misses = 0
        answer = session.pending_clarify_prompt
    elif len(candidates) == 1:
        # No rule context yet — stash as no-value pending for next turn.
        _clear_pending_clarify(session)
        session.pending_change_no_value_vn = candidates[0].variable_name
        answer = (
            f"Which value would you like for "
            f"**{_cpq_engine.disambiguated_label(candidates[0], attrs)}**?"
        )
    else:
        # No catalog-grounded candidates — still ask, but without binding
        # memory to invented names.
        _clear_pending_clarify(session)
        answer = (
            clarifying_question
            or "Which field and value should I use? Please name the attribute."
        )

    _vn_key = candidates[0].variable_name if candidates else None
    note_clarify(session, _vn_key or "_pending_clarify")
    if should_force_numbered_options(session, _vn_key or "_pending_clarify") and candidates:
        answer = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_prompt = answer
    if should_offer_guided_mode(session):
        answer = f"{answer}\n\n{guided_mode_offer_message()}"
    _persist_cpq_history(req.workspace_id, req.question, answer)
    return _with_classify_usage({
        "answer": answer, "terms": list(session.pending_clarify_vns),
        "tools_called": [tool_name],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }, prompt_tokens, completion_tokens)


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

    Every returned response is checked by
    ``enforce_conversational_invariant`` — a config-seeking question without
    consumable pending state logs ``cpq_orphan_question``.
    """
    return enforce_conversational_invariant(_run_cpq_turn_inner(req, reader))


def _pending_reply_looks_like_new_request(
    question: str, pending_attr: Any, attrs: list, filled: dict, filled_multi: dict,
) -> bool:
    """True only if `question` has an explicit change-verb/arrow AND names
    some OTHER real attr (never `pending_attr` itself) — i.e. a genuine new
    request, not a bare reply meant to answer the currently-pending
    question. Shared by STEP 5's own answer-lock and the LLM-first
    gateway's pre-STEP-5 gate (docs/config_consistency_issues_2026-07-30.md
    issue 4 follow-up): the gateway ran unconditionally BEFORE STEP 5 with
    no awareness of `session.pending_variables` at all, so a bare reply
    like "VHF" — meant to answer an actively-pending single-select
    question — could be reclassified fresh by the gateway and dispatched
    to a different, plausible-but-wrong sibling attribute (confirmed live:
    "VHF" is a legal option on modelSelectionFrequencyBandMsl_astro too),
    leaving the real pending attribute's stale value untouched and
    producing the exact "asked the same question again" loop this doc's
    Issue 4 already fixed one cause of.
    """
    if pending_attr is None:
        return False
    other_attrs = [a for a in attrs if a.variable_name != pending_attr.variable_name]
    return bool(
        (_cpq_engine._CHANGE_VERB_RE.search(question)
         or _cpq_engine._ARROW_RE.search(question))
        and (
            _cpq_engine.detect_change_target_without_value(question, other_attrs, filled)
            or _cpq_engine.detect_change_request(
                question, other_attrs, filled, filled_multi=filled_multi)
            or _cpq_engine.detect_change_requests_multi(
                question, other_attrs, filled, filled_multi=filled_multi)
        )
    )


def _run_cpq_turn_inner(req: AskRequest, reader: Any) -> dict[str, Any]:
    """Inner CPQ turn body — see ``_run_cpq_turn`` for the step contract."""
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
    record_utterance(session, req.question)

    # Residual Bug A: if earlier turns were standard Ask (no CpqSession),
    # recover country + long order text from req.history before any gate.
    _mine_history_for_cpq_context(session, req.history, _cpq_engine)

    # First-class UNDO — restore last session snapshot before any other routing.
    if detect_undo(req.question):
        if restore_last_snapshot(session):
            answer = undo_success_message(session)
        else:
            answer = undo_empty_message()
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_undo()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Accept deterministic guided mode (loop-exit offer).
    if detect_guided_mode_accept(req.question) and not session.guided_mode:
        session.guided_mode = True
        session.unresolved_turns = 0
        answer = (
            "Guided mode is on — I'll ask one clear question at a time "
            "using the deterministic catalog flow (no free-form intent jumps)."
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_guided_mode()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

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

    # Stash full order utterance early (even before family resolves) so a
    # later short family reply does not lose country/customer context.
    from aryx.cpq.intent_gateway import soft_quote_heuristic as _soft_q
    if (
        (session.country or _soft_q(req.question) or "country" in hints)
        and (
            not session.product_anchor_question
            or len(req.question.strip()) > len(session.product_anchor_question.strip())
        )
    ):
        session.product_anchor_question = req.question

    # ── Mid-session product-switch gate ───────────────────────────────────────
    # A PRIOR turn detected a different product than session.product_name and
    # asked the user to confirm before discarding the in-progress config. THIS
    # turn's raw reply is that yes/no answer, not a new CPQ hint (Andie-planned
    # fix for: "CPQ for two products is not working in the single session").
    _PRODUCT_SNAPSHOT_CAP = 5

    def _complete_product_switch(new_product: str, new_country: str) -> None:
        """Snapshot the outgoing product's state, restore the incoming
        product's own prior state if it was visited earlier this session,
        and commit the switch. `new_country` is carried over as-is (already
        validated by the caller, or simply never set) — never blindly
        cleared, so a client who already gave a valid country for the new
        product doesn't have to repeat it.

        Restored values are NOT trusted blindly — Step 2/3 below feed
        session.filled into auto_fill as `already_filled` on every turn
        regardless of where it came from, so a restored value that's no
        longer valid under current rules/constraints is naturally dropped
        and re-asked, exactly like any other turn's continuation (see
        docs/CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md §3)."""
        session.cascade_log.append({
            "event": "product_switch", "from": session.product_name,
            "to": new_product, "turn": session.turn,
        })
        # Snapshot the OUTGOING product before wiping it — even a
        # product visited only once is captured, ready for a much later
        # switch-back. Skipped on the very first-ever turn (no prior
        # product to snapshot). Re-inserted (not just updated) so dict
        # iteration order tracks recency for the cap below.
        if session.product_name:
            session.product_snapshots.pop(session.product_name, None)
            session.product_snapshots[session.product_name] = {
                "filled": dict(session.filled),
                "filled_multi": dict(session.filled_multi),
                "display_filled": dict(session.display_filled),
                "filled_source": dict(session.filled_source),
                "country": session.country,
                "negated_vns": list(session.negated_vns),
                "product_entity_id": session.product_entity_id,
            }
            while len(session.product_snapshots) > _PRODUCT_SNAPSHOT_CAP:
                oldest = next(iter(session.product_snapshots))
                session.product_snapshots.pop(oldest)

        snap = session.product_snapshots.get(new_product)
        if snap:
            session.filled = dict(snap["filled"])
            session.filled_multi = dict(snap["filled_multi"])
            session.display_filled = dict(snap["display_filled"])
            session.filled_source = dict(snap["filled_source"])
            session.negated_vns = list(snap["negated_vns"])
            session.product_entity_id = snap["product_entity_id"]
            # Only fall back to the snapshot's own country when THIS turn's
            # caller didn't already determine one — both call sites
            # (confirm_switch's carried-over country, switch_country's
            # freshly-validated replacement) always pass a non-empty value
            # when they have one; new_country is empty here only when
            # neither had anything to contribute (docs/CPQ_MULTI_PRODUCT_
            # SESSION_SNAPSHOT_PLAN.md §"Country carry-over — RESOLVED").
            # The snapshot's country needs no re-validation either: it was
            # captured while THIS SAME product was previously configured,
            # so it was already valid for it.
            if not new_country:
                new_country = snap["country"]
            logger.info(
                "cpq_switch: restored prior snapshot for product=%r turn=%s "
                "(%d filled attrs)", new_product, session.turn, len(snap["filled"]),
            )
        else:
            session.filled = {}
            session.filled_multi = {}
            session.display_filled = {}
            session.filled_source = {}
            session.negated_vns = []
            session.product_entity_id = 0

        session.pending_variables = []
        session.status = "configuring"
        session.country = new_country
        # NOTE: catalog_prefix is not a CpqSession field — it's derived
        # fresh from attrs[0].catalog_prefix every turn in Step 2 below,
        # so there's nothing session-scoped to reset here.
        session.product_name = new_product
        session.pending_switch_product = ""
        session.pending_switch_candidates = []
        session.pending_anchor = ""
        logger.info(
            "cpq_switch: switched turn=%s new_product=%r country=%r — config state %s",
            session.turn, new_product, new_country or "(none — will be asked fresh)",
            "restored from snapshot" if snap else "reset",
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
            session.pending_switch_question = ""
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
            # Before treating this as a flat decline, check whether the
            # reply itself names a DIFFERENT real, ingested product — e.g.
            # replying to "Switch to X?" with "Quote Y for a US customer"
            # is not a decline, it's a new switch request that got swallowed
            # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 1). Only re-prompt when
            # the detected product differs from both the current product and
            # the one just declined; otherwise fall through to a normal
            # decline exactly as before.
            _decline_alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
            _redetected = _cpq_engine.detect_product_mention(
                req.question, hints, reader, req.workspace_id,
                alias_map=_decline_alias_map,
            )
            _old_pending = session.pending_switch_product
            if (
                _redetected
                and _redetected != session.product_name
                and _redetected != _old_pending
            ):
                session.pending_switch_product = _redetected
                session.pending_switch_question = req.question
                logger.info(
                    "cpq_switch: decline-reply named a different product "
                    "turn=%s old_pending=%r new_pending=%r",
                    session.turn, _old_pending, _redetected,
                )
                answer = (
                    f"It looks like you're asking about **{_redetected}**, but "
                    f"this session is configuring **{session.product_name}**. "
                    f"Switch to **{_redetected}** and discard the current "
                    f"configuration? (yes/no)"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_switch_reoffer()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            session.pending_switch_product = ""
            session.pending_switch_question = ""
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
        # Intent-first gate (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 1): check
        # whether this message reads as a genuine question BEFORE trusting
        # any anchor-detection result at all — not just in the blind-accept
        # fallback below. Confirmed live this needed to run first, not
        # second: detect_product_mention itself matched "Svx Video Remote
        # Speaker Microphone" (quoted back from the assistant's own PRIOR
        # answer) inside "You said something about Svx Video RSM, how is it
        # connected to astra?" and confidently resolved it to
        # videoSolutions_BOM — a fuzzy incidental mention inside a question,
        # not the user's actual intent — so gating only on "detection
        # failed" was never going to catch this case. Routes to the same
        # graph-grounded Q&A path (_handle_cpq_qa) used everywhere else in
        # this file — attrs=[] is safe here since no product/catalog is
        # chosen yet, and _handle_cpq_qa's generic graph search doesn't
        # require it.
        if (
            session.pending_anchor == "product"
            and _cpq_engine.detect_qa_question(req.question, None, strict=True)
        ):
            logger.info(
                "cpq_intent_gate: question-shaped message %r intercepted "
                "before product-anchor detection (turn=%s) -> routing to Q&A",
                req.question, session.turn,
            )
            return _handle_cpq_qa(req, session, [], reader, resume_review=False)
        # PROMPT 7: reply to a prior "did you mean" / family list first
        detected = ""
        if session.pending_scope_candidates and session.pending_scope_kind in (
            "product_suggestions", "family_disambiguation", "",
        ):
            _sres0 = resolve_against_scope(
                req.question, list(session.pending_scope_candidates),
            )
            if _sres0.matched:
                detected = _sres0.matched
                clear_pending_scope(session)
            elif _sres0.suggestions:
                return _scoped_reask_response(
                    req, session, req.question,
                    scope_label="product family",
                    tools_called="cpq_product_did_you_mean()",
                )
        if not detected:
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
            # PROMPT 7: pet names / typos ("Asr"/"asty") → did you mean,
            # with pending_scope so the next reply is matched in-scope.
            _alias = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
            suggestions = _cpq_engine.suggest_product_candidates(
                req.question, reader, req.workspace_id, limit=5, alias_map=_alias,
            )
            # Also allow prefix / in-scope fuzzy against family names for
            # short nicknames that fall below the mid-band threshold.
            if not suggestions and families:
                _sres = resolve_against_scope(req.question, list(families))
                if _sres.matched:
                    detected = _sres.matched
                elif _sres.suggestions:
                    suggestions = list(_sres.suggestions)
            if detected:
                pass  # fall through to anchor with fuzzy family match
            elif suggestions:
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
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_product_did_you_mean()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            else:
                fam_list = (
                    ", ".join(f"*{f}*" for f in families)
                    if families else "*APX Next*, *MOTOTRBO*, *SL3500e*"
                )
                if families:
                    set_pending_scope(
                        session,
                        kind="product_suggestions",
                        candidates=list(families),
                        origin_question=req.question,
                        attr_vn="",
                        asked_turn=session.turn,
                    )
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
        # If we fuzzy-matched a family via scope above, detected is set.
        if not session.product_name and not detected:
            # Defensive — should not reach here without return.
            pass
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

    # Read-only intent-count diagnostic (docs/CPQ_LLM_INTENT_FIRST_PLAN.md
    # Fix 4, incremental first step) — measures how many distinct intents
    # this message actually contains against real traffic, WITHOUT
    # changing any routing behavior below. Never allowed to affect the
    # turn: wrapped so a failure here can't break anything real.
    try:
        _intent_hits = _cpq_engine.count_turn_intents(
            req.question, attrs, session.filled, session.filled_multi,
        )
        if len(_intent_hits) >= 2:
            logger.info(
                "cpq_intent_count: message %r matched %d distinct intents: %s "
                "-- only the first will actually be addressed today",
                req.question, len(_intent_hits), _intent_hits,
            )
        elif _intent_hits:
            logger.debug("cpq_intent_count: message %r matched: %s", req.question, _intent_hits)
    except Exception:  # noqa: BLE001 — diagnostic only, must never break the turn
        logger.debug("cpq_intent_count: diagnostic failed", exc_info=True)

    # Phase 1 shadow-mode universal-intent diagnostic (docs/
    # CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md) — same read-only, never-
    # affects-the-turn guarantee as count_turn_intents just above. Logs
    # its own classification for later comparison against the real
    # deterministic outcome (logged by run_ask after this function
    # returns) via matching run_id — never touches routing here.
    # Gated on cpq_shadow_intent_enabled (default off): live-confirmed
    # this unconditional LLM call took the CPQ/BML test suite from ~10s
    # to ~128s with zero behavioral change — a real test-speed/CI-cost
    # regression, separate from the "not a concern in production" stance.
    if get_settings().cpq_shadow_intent_enabled:
        _shadow_classify_cpq_turn(req, session, attrs)

    # A product-switch (or the initial turn's own NL detection) already
    # PROVED session.product_name against this catalog — asking the
    # productSelectionProduct_all question again on the very next turn
    # would ignore that proof and re-derive it from a reply ("yes") that
    # carries no product hint at all. Seed it directly via the same fuzzy
    # option-matcher normal answers use, mirroring the confirmed-country
    # carry-over above. Guarded on "not yet filled" so this only fires once
    # (turn 1, or the turn right after _complete_product_switch reset
    # session.filled) and never clobbers a value a later turn's real answer
    # already set.
    #
    # Seed productSelectionProduct_all only AFTER Hardware is known on
    # hardware-based catalogs (mandatory HW). Seeding from family name
    # early caused Product to look "answered" or raced ahead of Hardware.
    # On non-hardware catalogs, keep prior seed-from-anchor behavior.
    _hw_attrs = [a for a in attrs if _cpq_engine._is_hardware_version_attr(a)]
    _hw_ready = (
        not _hw_attrs
        or any(a.variable_name in session.filled for a in _hw_attrs)
    )
    if (
        _hw_ready
        and "productSelectionProduct_all" not in session.filled
    ):
        _product_attr = next(
            (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
        )
        if _product_attr is not None:
            _seed_candidates = [
                c for c in (
                    session.pending_switch_question,
                    session.product_anchor_question,
                    session.product_name,
                ) if c
            ]
            for _candidate_text in _seed_candidates:
                _match = _cpq_engine.apply_answer(_product_attr, _candidate_text)
                if _match:
                    _item_value, _display_name = _match
                    session.filled["productSelectionProduct_all"] = _item_value
                    session.display_filled["productSelectionProduct_all"] = _display_name
                    session.filled_source["productSelectionProduct_all"] = "product_anchor"
                    logger.info(
                        "cpq: seeded productSelectionProduct_all=%r from %r "
                        "turn=%s — skips a redundant re-ask",
                        _item_value, _candidate_text, session.turn,
                    )
                    break

    # session.pending_switch_question is captured above only to seed
    # productSelectionProduct_all — Region/Country hints from that same
    # original text are merged in further below (AFTER this turn's own
    # switch-redetection check), never here: merging them this early once
    # leaked extra signal into `hints` that the switch-redetection probe
    # a few lines below also reads, causing detect_product_mention to
    # spuriously re-fire on this SAME turn's plain "yes"/confirmation
    # reply (live-confirmed regression, caught in this session's own
    # verification — see the merge site further down for the real fix).
    _switch_trigger_question = session.pending_switch_question
    session.pending_switch_question = ""

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
                session.pending_switch_question = req.question
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
                # PROMPT 7: also set pending_scope so a near-miss typo on
                # the reply re-asks within these suggestions only.
                set_pending_scope(
                    session,
                    kind="product_suggestions",
                    candidates=list(suggestions),
                    origin_question=req.question,
                    attr_vn="",
                    asked_turn=session.turn,
                )
                if len(suggestions) == 1:
                    session.pending_switch_product = suggestions[0]
                    session.pending_switch_question = req.question
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

    # Country-once: re-scan this turn + anchor + switch + mined history
    # texts before prompting. Covers turn 1 standard-Ask (no session) then
    # "aSTRO25_bom" later — history mine at turn start + these sources.
    if not session.country:
        _hist_user = _user_texts_from_history(req.history)
        for _country_src in (
            req.question,
            session.product_anchor_question,
            session.pending_switch_question,
            *_hist_user,
        ):
            if not _country_src:
                continue
            _ch = _cpq_engine.extract_hints(_country_src)
            if _ch.get("country"):
                session.country = _ch["country"]
                hints.setdefault("country", _ch["country"])
                logger.info(
                    "cpq: latched country=%r from prior utterance turn=%s",
                    session.country, session.turn,
                )
                break

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

    # The same original switch-triggering text ("Quote APX Next Enhanced
    # radios for a US customer") often also answers the NEW catalog's own
    # Region/Country-shaped attrs, not just Product — but everything above
    # was extracted from THIS turn's `req.question` (the plain "yes"/
    # product-name confirmation reply, which carries no such signal).
    # Live-confirmed gap (2026-07-26): a product switch completed
    # correctly but then re-asked Region and Ultimate Destination Country
    # even though the customer's own original sentence already said "US".
    # Merged HERE, after this turn's own hint extraction AND after the
    # switch-redetection check above (not merged earlier — an earlier
    # attempt merged it before that check and caused detect_product_mention
    # to spuriously re-fire on this same "yes" turn, since it also reads
    # `hints`). setdefault so this turn's own, more specific hints always
    # win; this only fills in what's otherwise still missing.
    if _switch_trigger_question:
        for k, v in _cpq_engine.extract_hints(_switch_trigger_question).items():
            hints.setdefault(k, v)
        _switch_catalog_hints, _ = _cpq_engine.extract_catalog_hints(
            _switch_trigger_question, attrs)
        for vn, iv in _switch_catalog_hints.items():
            hints.setdefault(vn, iv)
        for vn, iv in _cpq_engine.extract_flag_hints(
            _switch_trigger_question, attrs, req.workspace_id, catalog_prefix,
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
        session.pending_model_leaf_candidates = []
    else:
        # Amendment 10 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a
        # catalog with 2+ model leaves (CommandCentral Aware:
        # commandCentralAware2024_BOM, commandCentralAware2026_BOM,
        # commandCentralDEMS_BOM, ...) has no single unambiguous leaf for
        # single_model_variable_name to seed — until now this silently
        # left _bm_model_variable_name unset and no question ever asked
        # which one was meant, so the turn fell through to the unrelated
        # "Product" attrs (which don't represent this identity in this
        # catalog's own data at all).
        _leaf_candidates = _cpq_engine.model_variable_candidates(
            reader, req.workspace_id, catalog_prefix)
        if _leaf_candidates:
            def _norm_leaf(s: str) -> str:
                n = re.sub(r"[^a-z0-9]", "", s.lower())
                return n[:-3] if n.endswith("bom") else n

            # A DIFFERENT, pre-existing mechanism (extract_flag_hints) can
            # already set _bm_model_variable_name from a literal camelCase
            # token in the text (e.g. "commandCentralAware2024") — but to
            # a value that isn't actually one of this catalog's real
            # bm_catalog leaves (missing the "_BOM" suffix, etc.), since
            # that mechanism never validates against the tree at all.
            # Live-confirmed regression (2026-07-26): this silently
            # bypassed the disambiguation below entirely, since something
            # was already "set" — just not to a real leaf. Validate
            # whatever's already there first; only treat it as resolved
            # when it genuinely normalizes to one of the real candidates.
            _existing_hint = hints.get("_bm_model_variable_name") or session.filled.get("_bm_model_variable_name")
            _resolved_leaf = next(
                (leaf for leaf in _leaf_candidates if _existing_hint and _norm_leaf(leaf) == _norm_leaf(_existing_hint)),
                None,
            )
            if _resolved_leaf:
                session.model_leaf_resolved = True
            elif session.pending_model_leaf_candidates:
                # A prior turn already asked — this reply should answer it.
                # PROMPT 7: exact → partial → fuzzy within the same leaf list
                # before LLM; on miss, scoped re-ask (never Product 325).
                _reply = req.question.strip()
                _leaf_scope = list(session.pending_model_leaf_candidates)
                _sres = resolve_against_scope(_reply, _leaf_scope)
                if _sres.matched:
                    _resolved_leaf = _sres.matched
                if _resolved_leaf is None:
                    _leaf_attr_candidates = [
                        ConfigAttr(
                            entity_id=0, variable_name=leaf, display_label=leaf,
                            required=False, default_value="",
                            options=[MenuOption(item_value=leaf, display_name=leaf)],
                        )
                        for leaf in _leaf_scope
                    ]
                    _llm_leaf = _llm_resolve_label_collision(
                        _reply, _leaf_attr_candidates, session, req.workspace_id)
                    if _llm_leaf and _llm_leaf in _leaf_scope:
                        _resolved_leaf = _llm_leaf
                if _resolved_leaf is None:
                    # Keep model-leaf candidates AND pending_scope in sync
                    set_pending_scope(
                        session,
                        kind="family_disambiguation",
                        candidates=_leaf_scope,
                        origin_question=req.question,
                        attr_vn="",
                        asked_turn=session.turn,
                    )
                    return _scoped_reask_response(
                        req, session, _reply,
                        scope_label="product line",
                        tools_called="cpq_model_leaf_ambiguous()",
                    )
            else:
                # First time seeing this ambiguity — try to auto-resolve
                # from what the customer already said (this turn's text,
                # plus the original switch-triggering text if a switch
                # brought us here) before ever interrupting with a question.
                _combined = (
                    req.question + " " + (_switch_trigger_question or "")
                    + " " + (session.product_anchor_question or "")
                )
                _combined_norm = _norm_leaf(_combined)
                _text_matches = [
                    leaf for leaf in _leaf_candidates
                    if len(_norm_leaf(leaf)) >= 5 and _norm_leaf(leaf) in _combined_norm
                ]
                if len(_text_matches) == 1:
                    _resolved_leaf = _text_matches[0]

            if _resolved_leaf:
                # Force-set, not setdefault: extract_flag_hints may have
                # already put an unvalidated value here (e.g. missing the
                # real leaf's "_BOM" suffix) — this is the validated,
                # canonical leaf identifier and must win.
                hints["_bm_model_variable_name"] = _resolved_leaf
                session.pending_model_leaf_candidates = []
                session.model_leaf_resolved = True
                clear_pending_scope(session)
            else:
                session.pending_model_leaf_candidates = _leaf_candidates
                set_pending_scope(
                    session,
                    kind="family_disambiguation",
                    candidates=list(_leaf_candidates),
                    origin_question=req.question,
                    attr_vn="",
                    asked_turn=session.turn,
                )
                _leaf_lines = "\n".join(f"{i+1}. {leaf}" for i, leaf in enumerate(_leaf_candidates))
                _static_leaf_answer = (
                    f"This family has more than one product line — which one are "
                    f"you configuring?\n\n{_leaf_lines}"
                )
                _leaf_answer = _compose_disambiguation_question(
                    req.question, "which specific product line/model they want",
                    _leaf_candidates,
                    {"Country": session.country, "Product": session.product_name},
                    _static_leaf_answer, req.workspace_id,
                )
                _persist_cpq_history(req.workspace_id, req.question, _leaf_answer)
                return {
                    "answer": _leaf_answer, "terms": [],
                    "tools_called": ["cpq_model_leaf_ambiguous()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }

    # ── Load all rule sets (needed for Step 3, 5, 6, 7) ───────────────────────
    hiding_rules = _cpq_engine.load_hiding_rules(req.workspace_id, catalog_prefix)
    rec_rules, con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, catalog_prefix)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)

    # Resolve a pending "which value?" clarifying question from a previous
    # turn's valueless change request (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md
    # Related finding 1) — the reply IS the new value directly, not a fresh
    # hint, so it must be captured here before any other detection runs,
    # regardless of session.status (checked first for the same reason
    # pending_change_collision_vns/pending_label_collision_vns are each
    # checked before their surrounding STEP logic).
    if session.pending_change_no_value_vn:
        _pcnv_attr = next(
            (a for a in attrs if a.variable_name == session.pending_change_no_value_vn), None,
        )
        session.pending_change_no_value_vn = ""
        if _pcnv_attr:
            # QA issue #3: re-derive constrained set for scoped match/retry.
            # §15: try/except so pure declines never crash on rule engine.
            try:
                _pcnv_constrained = _cpq_engine.apply_constraint_rules(
                    attrs, con_rules, session.filled, bml_eval,
                ).get(_pcnv_attr.entity_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cpq: constraint recompute failed for pending change "
                    "value on %r, proceeding unconstrained: %r",
                    _pcnv_attr.variable_name, exc,
                )
                _pcnv_constrained = None
            # PROMPT 6: extract wanted (+ rejected); exclude rejected option.
            _pcnv_wanted, _pcnv_rejected = _extract_replacement_clause(req.question)
            _pcnv_match_text = _pcnv_wanted or req.question
            _pcnv_constrained = _constrain_excluding_rejected(
                _pcnv_attr, _pcnv_rejected, _pcnv_constrained,
            )
            # QA issue #2: try real value FIRST; only treat as decline when
            # nothing resolves (compound "don't want Standard; use Premium").
            if _pcnv_attr.select_type == "multi":
                _pcnv_matched = bool(_cpq_engine.apply_multi_answer(
                    _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
                ))
            else:
                _pcnv_matched = _cpq_engine.apply_answer(
                    _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
                ) is not None
            if not _pcnv_matched and _is_change_value_decline(req.question):
                _pcnv_current = session.display_filled.get(_pcnv_attr.variable_name)
                answer = (
                    f"No problem — I'll leave "
                    f"**{_cpq_engine.disambiguated_label(_pcnv_attr, attrs)}** "
                    f"as it is"
                    + (f" (**{_pcnv_current}**)." if _pcnv_current else ".")
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_change_declined()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            # Multi-intent follow-up (docs/CPQ_LLM_INTENT_FIRST_PLAN.md
            # Fix 4) is now handled INSIDE _handle_cascade itself — it's the
            # single common convergence point every change-request entry
            # point reaches, so re-queuing pending_multi_intent_vn there
            # covers this caller too without needing its own copy here.
            return _handle_cascade(
                req, session, attrs, _pcnv_attr, _pcnv_match_text,
                hiding_rules, rec_rules, con_rules,
                constrained_item_values=_pcnv_constrained,
            )

    # Gateway clarify reply — resolve BEFORE any blind re-classification.
    # Live gap: "change hardware" → clarify → "Hardware Version" had no
    # memory and fell to the review nudge (ask_api.py gateway clarify branch).
    _pending_clarify_resp = _handle_pending_clarify_turn(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
    )
    if _pending_clarify_resp is not None:
        return _pending_clarify_resp

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
    # Same Amendment 10 follow-up as skip_always_ask above — a resolved
    # model-leaf identity means the catalog's "Product"-labeled attrs are
    # proven irrelevant here, so they must not ship in the payload either,
    # not just skip being asked.
    if session.model_leaf_resolved:
        _hidden_for_payload = _hidden_for_payload | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
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

    # ── STEP 6 / 7 / 8 routing: awaiting_approval / post_approval status ────
    # "approved" is a legacy dead-end value (pre-
    # docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md D1) that used to be set once
    # at STEP 8 and never checked again — normalized here so a session
    # confirmed before this shipped (still held by a client that hasn't
    # refreshed) converges onto the real status instead of silently
    # falling through to the generic top-of-turn path.
    if session.status == "approved":
        session.status = "post_approval"
    if session.status in ("awaiting_approval", "post_approval"):
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
                session.product_name, req.workspace_id, sources=session.filled_source,
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

        # STEP 8: explicit approval → generate BOM payload. Saying
        # "confirm" again while already post_approval is idempotent — it
        # just re-shows the CURRENT (possibly edited) JSON, nothing new
        # to run (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md §4.1).
        if _cpq_engine.detect_approval(req.question):
            # Final BOM gate — constraint re-run + provenance hard-fail.
            # Never emit a payload that fails verification.
            catalog_prefix_gate = attrs[0].catalog_prefix if attrs else ""
            bml_gate = _cpq_engine.build_bml_evaluator(
                req.workspace_id, catalog_prefix_gate,
            )
            gate = validate_before_payload(
                _cpq_engine, attrs, session, con_rules, bml_gate,
            )
            if not gate.ok and gate.stale_violations:
                # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §15
                # — review finding: multiple active constraints can
                # legitimately intersect to an EMPTY allowed set (a genuine
                # rule conflict, not a stale-but-fixable value). Auto-
                # clearing and re-asking with `constrained_item_values=[]`
                # produced an unanswerable "Please provide a value" loop —
                # confirmed live, no reply could ever match. Report the
                # conflict instead; nothing is mutated (no push_snapshot,
                # no pops) since there's no productive value to ask for.
                _conflicted = [v for v in gate.stale_violations if not v.allowed]
                if _conflicted:
                    _conflict_labels = [
                        _cpq_engine.disambiguated_label(v.attr, attrs)
                        for v in _conflicted
                    ]
                    answer = (
                        "⚠️ **Rule conflict detected.**\n\n"
                        + (
                            f"**{_conflict_labels[0]}** has no valid options "
                            if len(_conflict_labels) == 1 else
                            "The following have no valid options "
                            + ", ".join(f"**{l}**" for l in _conflict_labels) + " "
                        )
                        + "left, given your other selections — the active "
                        "rules conflict with each other.\n\nPlease change one "
                        "of your earlier selections, or say **undo** to "
                        "restore the previous snapshot."
                    )
                    _persist_cpq_history(req.workspace_id, req.question, answer)
                    return {
                        "answer": answer, "terms": [],
                        "tools_called": ["cpq_rule_conflict()"],
                        "usage": {
                            "prompt_tokens": 0, "completion_tokens": 0,
                            "latency_ms": 0, "menial_model": "cpq-engine",
                            "answer_model": "cpq-engine",
                        },
                        "grounding": None, "session_data": session.to_dict(),
                        "cpq_payload": None,
                    }
                # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md
                # §11 — auto-clear + re-ask rather than hard-block: the
                # engine knows these values are stale but not what the
                # replacement should be, so it asks instead of guessing or
                # refusing outright.
                # §12 — push_snapshot BEFORE mutating, same discipline as
                # every other mutation site (_handle_cascade etc.), so
                # "undo" right after this re-ask reverts just this clear
                # instead of skipping past it to an earlier state.
                push_snapshot(session, reason="stale_constraint_reask")
                _stale_display: dict[str, str] = {}
                _stale_vns: list[str] = []
                for _v in gate.stale_violations:
                    _vn = _v.attr.variable_name
                    _stale_display[_vn] = (
                        session.display_filled.get(_vn) or _v.current_value
                    )
                    # §12 — a multi-select's value lives in filled_multi,
                    # not filled; popping the wrong dict left it untouched.
                    # §17 review finding: popping the ENTIRE filled_multi
                    # entry discarded every still-valid selection alongside
                    # the invalid one(s) — a customer with 5 valid carrier
                    # selections and 1 now-invalid one lost all 5. `_v.
                    # current_value` (bom_gate.py) already isolates only the
                    # invalid item(s); keep everything else instead of
                    # wiping the whole key.
                    if _v.attr.select_type == "multi":
                        _kept = [
                            iv for iv in session.filled_multi.get(_vn, [])
                            if iv in _v.allowed
                        ]
                        if _kept:
                            session.filled_multi[_vn] = _kept
                            session.display_filled[_vn] = ", ".join(
                                next(
                                    (o.display_name for o in _v.attr.options
                                     if o.item_value == iv),
                                    iv,
                                )
                                for iv in _kept
                            )
                        else:
                            session.filled_multi.pop(_vn, None)
                            session.display_filled.pop(_vn, None)
                    else:
                        session.filled.pop(_vn, None)
                        session.display_filled.pop(_vn, None)
                    session.filled_source.pop(_vn, None)
                    _stale_vns.append(_vn)
                session.pending_variables = _stale_vns + [
                    v for v in session.pending_variables if v not in _stale_vns
                ]
                session.status = "configuring"
                session.complete = False
                _first = gate.stale_violations[0]
                _stale_opts_prompt = _cpq_engine.next_question_prompt(
                    _first.attr, constrained_item_values=_first.allowed,
                )
                _rest_labels = [
                    _cpq_engine.disambiguated_label(_v.attr, attrs)
                    for _v in gate.stale_violations[1:]
                ]
                _also_note = (
                    f"\n\n*(I'll also ask about {', '.join(f'**{l}**' for l in _rest_labels)} next.)*"
                    if _rest_labels else ""
                )
                answer = (
                    f"A couple of your earlier selections no longer match your "
                    f"other choices — let's update "
                    f"{'them' if _rest_labels else 'it'} before I generate the BOM.\n\n"
                    f"**{_cpq_engine.disambiguated_label(_first.attr, attrs)}** is "
                    f"currently *{_stale_display[_first.attr.variable_name]}*, which "
                    f"isn't valid anymore given your other choices:\n\n"
                    f"{_stale_opts_prompt}{_also_note}"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [],
                    "tools_called": ["cpq_stale_constraint_reask()"],
                    "usage": {
                        "prompt_tokens": 0, "completion_tokens": 0,
                        "latency_ms": 0, "menial_model": "cpq-engine",
                        "answer_model": "cpq-engine",
                    },
                    "grounding": None, "session_data": session.to_dict(),
                    "cpq_payload": None,
                }
            if not gate.ok:
                session.complete = False
                session.status = "awaiting_approval"
                _persist_cpq_history(
                    req.workspace_id, req.question, gate.catch_message,
                )
                return {
                    "answer": gate.catch_message, "terms": [],
                    "tools_called": ["cpq_bom_gate_blocked()"],
                    "usage": {
                        "prompt_tokens": 0, "completion_tokens": 0,
                        "latency_ms": 0, "menial_model": "cpq-engine",
                        "answer_model": "cpq-engine",
                    },
                    "grounding": None, "session_data": session.to_dict(),
                    "cpq_payload": None,
                }
            session.status = "post_approval"
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

        # Pending OPTIONS-QUERY collision resolution — a PRIOR turn's
        # detect_label_collision (inside _handle_cpq_qa) asked "which one
        # did you mean?" and stored the candidates + original question.
        # Checked BEFORE STEP 7 so this turn's reply resolves THAT prompt
        # instead of _handle_cpq_qa treating it as a fresh, unrelated
        # question (live-verified gap, 2026-07-23 — same class of bug
        # already fixed for the change-request collision below, never
        # applied to this separate options-query collision path).
        # Deterministic first (exact variable_name or 1-based list index —
        # the common case, zero latency/cost); an LLM fallback only for
        # looser phrasing the deterministic check can't resolve, gated
        # exactly like _llm_classify_change_intent (deterministic first,
        # never invents a name outside the candidate list).
        if session.pending_label_collision_vns:
            _lc_reply = req.question.strip()
            _lc_resolved_vn = None
            if _lc_reply in session.pending_label_collision_vns:
                _lc_resolved_vn = _lc_reply
            elif _lc_reply.isdigit():
                _lc_idx = int(_lc_reply) - 1
                if 0 <= _lc_idx < len(session.pending_label_collision_vns):
                    _lc_resolved_vn = session.pending_label_collision_vns[_lc_idx]
            if _lc_resolved_vn is None:
                _lc_candidates = [
                    a for a in attrs
                    if a.variable_name in session.pending_label_collision_vns
                ]
                if _lc_candidates:
                    _lc_resolved_vn = _llm_resolve_label_collision(
                        _lc_reply, _lc_candidates, session, req.workspace_id)
            if _lc_resolved_vn:
                _lc_resolved_attr = next(
                    (a for a in attrs if a.variable_name == _lc_resolved_vn), None)
                _lc_orig_question = session.pending_label_collision_question
                session.pending_label_collision_vns = []
                session.pending_label_collision_question = ""
                if _lc_resolved_attr is not None and _lc_orig_question:
                    _lc_req = req.model_copy(update={"question": _lc_orig_question})
                    return _handle_cpq_qa(
                        _lc_req, session, [_lc_resolved_attr], reader, resume_review=True)
                if _lc_resolved_attr is not None:
                    # System-initiated collision (Amendment 4 follow-up,
                    # _label_collision_for) — no original user question to
                    # resume, since the engine itself picked pending[0] and
                    # found it label-collided, not a user's own Q&A query.
                    # Just ask the customer's now-disambiguated attr next.
                    session.pending_variables = [_lc_resolved_attr.variable_name] + [
                        v for v in session.pending_variables if v != _lc_resolved_attr.variable_name
                    ]
                    _lc_ctx = _cpq_engine.build_context_sentence(
                        _lc_resolved_attr, attrs, session.filled, session.display_filled,
                        hiding_rules, rec_rules,
                    )
                    _lc_q_block = _cpq_engine.next_question_prompt(_lc_resolved_attr, _lc_ctx, None)
                    _persist_cpq_history(req.workspace_id, req.question, _lc_q_block)
                    return {
                        "answer": _lc_q_block, "terms": [],
                        "tools_called": ["cpq_pending_question_collision_resolved()"],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                    }
            # Unrecognized reply (deterministic AND LLM fallback both
            # came up empty) — clear the stale pending state and fall
            # through to normal routing rather than getting stuck forever.
            session.pending_label_collision_vns = []
            session.pending_label_collision_question = ""

        # STEP 7: Q&A during review — answer graph question, then show review again
        if _cpq_engine.detect_qa_question(req.question, strict=False):
            return _handle_cpq_qa(req, session, attrs, reader, resume_review=True)

        # Pending collision resolution — a PRIOR turn asked "which one did
        # you mean?" (detect_change_request_collision, below) and stored
        # the candidates + original question. This turn's reply answers
        # that, not a fresh CPQ hint: accept either the literal
        # variable_name or a 1-based list index (the order the candidates
        # were shown in). Live-verified gap (2026-07-22): the collision
        # prompt had no memory at all, so the very next turn — even a
        # verbatim variable_name — fell through to the generic nudge.
        if session.pending_change_collision_vns:
            _resolved_vn = None
            _reply = req.question.strip()
            if _reply in session.pending_change_collision_vns:
                _resolved_vn = _reply
            elif _reply.isdigit():
                _idx = int(_reply) - 1
                if 0 <= _idx < len(session.pending_change_collision_vns):
                    _resolved_vn = session.pending_change_collision_vns[_idx]
            if _resolved_vn is None:
                # LLM fallback for looser phrasing (the whole pasted
                # option line, "the second one", etc.) — same as the
                # options-query collision path (pending_label_collision_
                # vns) already had. Missing here in review (PR #117):
                # this path only ever handled exact match/index, so a
                # pasted full line hit "Unrecognized reply" and silently
                # cleared the pending state instead of resolving.
                _candidates = [
                    a for a in attrs
                    if a.variable_name in session.pending_change_collision_vns
                ]
                if _candidates:
                    _resolved_vn = _llm_resolve_label_collision(
                        _reply, _candidates, session, req.workspace_id)
            if _resolved_vn:
                _resolved_attr = next(
                    (a for a in attrs if a.variable_name == _resolved_vn), None)
                _orig_question = session.pending_change_collision_question
                session.pending_change_collision_vns = []
                session.pending_change_collision_question = ""
                if _resolved_attr is not None:
                    _resolved_change = _cpq_engine.detect_change_request(
                        _orig_question, [_resolved_attr], session.filled,
                        filled_multi=session.filled_multi)
                    if _resolved_change:
                        _, _resolved_value = _resolved_change
                        # Multi-intent follow-up (docs/CPQ_LLM_INTENT_FIRST_
                        # PLAN.md Fix 4) is handled INSIDE _handle_cascade —
                        # it re-queues pending_multi_intent_vn itself, the
                        # single common convergence point every caller
                        # (including this one) reaches.
                        return _handle_cascade(
                            req, session, attrs, _resolved_attr, _resolved_value,
                            hiding_rules, rec_rules, con_rules,
                        )
                    # No parseable value for the resolved attr (e.g. the
                    # original message's target was really a per-row
                    # quantity, not this attr's own value) — re-ask it as a
                    # genuine pending question, same as any other unanswered
                    # attr, so the NEXT reply is captured by STEP 5 instead
                    # of being orphaned (live-verified gap, 2026-07-22: the
                    # prior version showed the same options list but never
                    # registered pending_variables, so the follow-up reply
                    # fell through to the generic nudge).
                    opts_prompt = (
                        _cpq_engine.next_question_prompt(_resolved_attr)
                        if _resolved_attr.options else ""
                    )
                    answer = (
                        f"Couldn't find a value for "
                        f"**{_cpq_engine.disambiguated_label(_resolved_attr, attrs)}** in "
                        f"\"{_orig_question}\". Please say what to change it to."
                        + (f"\n\n{opts_prompt}" if opts_prompt else "")
                        + _queue_followup_note(session, attrs)
                    )
                    session.status = "configuring"
                    session.pending_variables = [
                        _resolved_attr.variable_name,
                        *[v for v in session.pending_variables
                          if v != _resolved_attr.variable_name],
                    ]
                    _persist_cpq_history(req.workspace_id, req.question, answer)
                    return {
                        "answer": answer, "terms": [],
                        "tools_called": ["cpq_change_label_collision_resolved()"],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                    }
            # Unrecognized reply — clear the stale pending state and fall
            # through to normal routing rather than getting stuck forever.
            session.pending_change_collision_vns = []
            session.pending_change_collision_question = ""

        # docs/config_consistency_issues_2026-07-30.md issue 4 follow-up —
        # this gateway used to run unconditionally here, BEFORE STEP 5 ever
        # got a chance to apply a bare reply to an actively-pending
        # single-select question. Live-confirmed: replying "VHF" to a
        # correctly-pending "Frequency Bands — choose one: VHF/UHF"
        # reprompt got reclassified fresh by the gateway and dispatched to
        # a different, plausible-but-wrong sibling attribute
        # (modelSelectionFrequencyBandMsl_astro also legally accepts
        # "VHF"), leaving the real pending attribute's stale value
        # untouched — the customer then confirms, the same staleness is
        # detected again, and the whole reprompt loops forever. Deferring
        # to STEP 5 whenever a reply doesn't clearly look like a fresh
        # request (same _pending_reply_looks_like_new_request check STEP 5
        # already uses for its own domain) closes that gap without
        # touching genuine new requests, which still reach the gateway.
        _pending_attr_for_gate = None
        if session.pending_variables and session.turn > 1:
            _pending_attr_for_gate = next(
                (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
            )
        _defer_gateway_to_pending_answer = (
            _pending_attr_for_gate is not None
            and not _pending_reply_looks_like_new_request(
                req.question, _pending_attr_for_gate, attrs,
                session.filled, session.filled_multi,
            )
        )

        # LLM-first mid-session gateway. N4: skip when top-level
        # classify_ask_route already ran this turn (one classification LLM
        # call per turn). Live sessions never mark top-level, so they still
        # get STEP-6 gateway. Guided mode stays deterministic-only.
        if (
            get_settings().cpq_llm_first_enabled
            and not session.guided_mode
            and not top_level_route_used()
            and not _defer_gateway_to_pending_answer
        ):
            _gw = gateway_classify_intent(
                req.question, attrs, session, _cpq_engine, req.workspace_id,
            )
            logger.info(
                "cpq_intent_gateway_turn: action=%s reason=%r category=%s "
                "vn=%r value_ref=%r cache_hit=%s tokens=(%d,%d) model=%s",
                _gw.action, _gw.reason,
                _gw.result.intent_category.value if _gw.result else None,
                _gw.result.variable_name if _gw.result else None,
                _gw.result.value_ref if _gw.result else None,
                _gw.cache_hit, _gw.prompt_tokens, _gw.completion_tokens,
                _gw.model_id,
            )
            if _gw.action == "clarify" and _gw.result:
                # Compound "change X and what is Y" messages (docs/CPQ_
                # COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §4) land
                # here as an ambiguous clarify — the gateway's own schema
                # can't hold two targets. Try an LLM-first split BEFORE
                # falling to the generic clarify prompt; cheap conjunction
                # pre-check keeps this from firing on ordinary ambiguous
                # single-intent messages that have no "and"/";" at all.
                _cq_lower = req.question.lower()
                if " and " in _cq_lower or ";" in req.question:
                    _split = _llm_split_compound_change_and_question(
                        req.question, req.workspace_id,
                    )
                    if _split is not None:
                        _change_text, _question_text = _split
                        _change_hint = _cpq_engine.detect_change_request(
                            _change_text, attrs, session.filled, session.filled_multi,
                        )
                        if _change_hint is not None:
                            _changed_attr, _new_value_hint = _change_hint
                            _change_req = req.model_copy(
                                update={"question": _change_text},
                            )
                            _change_result = _handle_cascade(
                                _change_req, session, attrs, _changed_attr,
                                _new_value_hint, hiding_rules, rec_rules, con_rules,
                            )
                            _qa_req = req.model_copy(
                                update={"question": _question_text},
                            )
                            _qa_result = _handle_cpq_qa(
                                _qa_req, session, attrs, reader,
                            )
                            _combined = (
                                f"{_change_result.get('answer', '')}\n\n"
                                f"{_qa_result.get('answer', '')}"
                            )
                            _persist_cpq_history(
                                req.workspace_id, req.question, _combined,
                            )
                            return {
                                **_qa_result,
                                "answer": _combined,
                                "tools_called": (
                                    list(_change_result.get("tools_called") or [])
                                    + list(_qa_result.get("tools_called") or [])
                                ),
                            }
                        # Split succeeded but the change clause didn't
                        # resolve deterministically — fall through to the
                        # existing clarify path unchanged (safe default).
                # docs/config_consistency_issues_2026-07-30.md issue 1 — never
                # offer a currently-hidden-for-this-product attribute as a
                # disambiguation candidate.
                _hidden_vns = _cpq_engine.apply_hiding_rules(
                    attrs, session.filled, hiding_rules, bml_eval,
                )[2]
                return _set_pending_clarify_and_answer(
                    req, session, attrs,
                    original_question=req.question,
                    clarifying_question=_gw.result.clarifying_question,
                    con_rules=con_rules,
                    bml_eval=bml_eval,
                    prompt_tokens=_gw.prompt_tokens,
                    completion_tokens=_gw.completion_tokens,
                    tool_name="cpq_intent_gateway_clarify()",
                    hidden_vns=_hidden_vns,
                    hiding_rules=hiding_rules,
                    rec_rules=rec_rules,
                )
            if _gw.action == "dispatch" and _gw.result:
                clear_clarify(session, _gw.result.variable_name)
                # Successful non-clarify path — drop any stale clarify memory.
                _clear_pending_clarify(session)
                _mapped = _gateway_to_intent_result(
                    _gw.result, attrs, _gw.value_display,
                )
                if _mapped is not None:
                    # AMBIGUOUS via dispatch path must also set pending memory.
                    if _mapped.category == IntentCategory.AMBIGUOUS:
                        # docs/config_consistency_issues_2026-07-30.md issue 1
                        _hidden_vns = _cpq_engine.apply_hiding_rules(
                            attrs, session.filled, hiding_rules, bml_eval,
                        )[2]
                        return _set_pending_clarify_and_answer(
                            req, session, attrs,
                            original_question=req.question,
                            clarifying_question=_mapped.clarifying_question,
                            con_rules=con_rules,
                            bml_eval=bml_eval,
                            prompt_tokens=_gw.prompt_tokens,
                            completion_tokens=_gw.completion_tokens,
                            tool_name="cpq_llm_first_ambiguous()",
                            hidden_vns=_hidden_vns,
                            hiding_rules=hiding_rules,
                            rec_rules=rec_rules,
                        )
                    _dispatched = _dispatch_intent_result(
                        req, session, attrs, _mapped,
                        hiding_rules, rec_rules, con_rules, bml_eval,
                        _gw.prompt_tokens, _gw.completion_tokens,
                    )
                    if _dispatched is not None:
                        return _dispatched
                    logger.info(
                        "cpq_intent_gateway_turn: dispatch mapped but handler "
                        "returned None — falling through to deterministic path",
                    )
            # action=fallback (or dispatch that couldn't map) → STEP 6+

        # STEP 6: change request → cascade
        # Bulk quantity check first — "change both the mounting types
        # quantity to 67" targets every already-selected row's quantity
        # attr, never the grid selector's own value, so it must run before
        # both the removal check (a different verb-and-verb-shape entirely)
        # and the collision check below (which would otherwise ask to
        # disambiguate between two identically-labeled "Mounting Type"
        # attrs even though only the real multi-select grid ever has
        # resolvable quantity links in the first place).
        _bulk_qty_match = _cpq_engine.detect_bulk_quantity_change(
            req.question, attrs, session.filled_multi)
        if _bulk_qty_match:
            _bulk_selector_vn, _bulk_item_values, _bulk_new_qty = _bulk_qty_match
            return _handle_bulk_quantity_change(
                req, session, attrs, _bulk_selector_vn, _bulk_item_values, _bulk_new_qty,
                hiding_rules, rec_rules, con_rules,
            )

        # Deselect check first — "remove X"/"deselect X" is a distinct
        # intent from both the collision check and detect_change_request
        # below (subtracting one option from an existing multi-select
        # selection, never a single-select value replacement), so it's
        # handled entirely separately before either of those runs.
        _removal_match = _cpq_engine.detect_multi_select_removal(
            req.question, attrs, session.filled_multi)
        if _removal_match:
            _removal_attr, _to_remove = _removal_match
            return _handle_multi_select_removal(
                req, session, attrs, _removal_attr, _to_remove,
                hiding_rules, rec_rules, con_rules,
            )

        # Attribute activation — "add X"/"activate X" re-enabling a real,
        # currently-excluded optional catalog attr (D2,
        # docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md). Same priority
        # position as the removal check above — a distinct intent from
        # both removal and a normal value-replacement change request.
        _activation_match = _cpq_engine.detect_attr_activation(
            req.question, attrs, session.filled, session.filled_multi,
            hiding_rules, req.workspace_id, catalog_prefix, bml_eval=bml_eval,
        )
        if _activation_match:
            return _handle_attr_activation(
                req, session, attrs, _activation_match,
                hiding_rules, rec_rules, con_rules,
            )

        # Attribute nullify — "clear X"/"unset X" blanking an optional
        # single-select attr's current value back to empty (D4). Same
        # priority position as activation.
        _clear_match = _cpq_engine.detect_attr_clear(
            req.question, attrs, session.filled, rec_rules, con_rules, bml_eval=bml_eval,
        )
        if _clear_match:
            return _handle_attr_clear(
                req, session, attrs, _clear_match,
                hiding_rules, rec_rules, con_rules,
            )

        # Identical-label collision check first — same reasoning as the
        # detect_attr_query collision check above, but scoped to change
        # requests (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2's fix never
        # actually covered this path — see detect_change_request_collision's
        # docstring). Must run before detect_change_request, which would
        # otherwise silently resolve the tie to whichever attr is first in
        # catalog order.
        _change_collision = _cpq_engine.detect_change_request_collision(
            req.question, attrs, session.filled, filled_multi=session.filled_multi)
        if _change_collision:
            _lines = "\n".join(
                f"{i}. **{a.variable_name}**"
                f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
                for i, a in enumerate(_change_collision, start=1)
            )
            answer = (
                f"There are {len(_change_collision)} different attributes labeled "
                f"**\"{_change_collision[0].display_label}\"** in this catalog — which one "
                f"did you mean to change? Reply with the number or the variable_name.\n\n{_lines}"
            )
            # Multi-target queue: scan the utterance for ALL other named
            # valueless change targets (excluding the collision candidates)
            # and enqueue them so none are silently dropped.
            _collision_vns = {a.variable_name for a in _change_collision}
            _scan_and_enqueue_remaining_targets(
                session, req.question, attrs, exclude_vns=_collision_vns,
            )
            answer += _queue_followup_note(session, attrs)
            session.pending_change_collision_vns = [a.variable_name for a in _change_collision]
            session.pending_change_collision_question = req.question
            _persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_change_label_collision()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }

        # Try multi-attribute first ("change X to A and Y to B" — up to
        # detect_change_requests_multi's cap) — only route to the multi
        # handler when it actually found 2+ distinct attrs; a single match
        # falls through to the existing, more heavily-tested single-change
        # path unchanged, so the common case has zero behavior change.
        _multi_matches = _cpq_engine.detect_change_requests_multi(
            req.question, attrs, session.filled, filled_multi=session.filled_multi)
        if len(_multi_matches) >= 2:
            # Enqueue any additional named no-value targets not already in the multi match.
            _multi_vns = {a.variable_name for a, _ in _multi_matches}
            _scan_and_enqueue_remaining_targets(
                session, req.question, attrs, exclude_vns=_multi_vns,
            )
            _multi_result = _handle_cascade_multi(
                req, session, attrs, _multi_matches,
                hiding_rules, rec_rules, con_rules,
            )
            if _multi_result is not None:
                return _append_unmatched_targets_note(
                    _multi_result, req.question, attrs,
                    {a.variable_name for a, _ in _multi_matches},
                )
        else:
            change_result = _cpq_engine.detect_change_request(
                req.question, attrs, session.filled, filled_multi=session.filled_multi)
            if change_result:
                changed_attr, new_value_hint = change_result
                # Enqueue sibling named targets before applying the primary.
                _scan_and_enqueue_remaining_targets(
                    session, req.question, attrs,
                    exclude_vns={changed_attr.variable_name},
                )
                return _append_unmatched_targets_note(
                    _handle_cascade(
                        req, session, attrs, changed_attr, new_value_hint,
                        hiding_rules, rec_rules, con_rules,
                    ),
                    req.question, attrs, {changed_attr.variable_name},
                )

        # LLM fallback: every regex detector above found nothing — try the
        # existing menial-tier classifier before giving up (Andie scoping,
        # 2026-07-22: regex-first, LLM-fallback via the model tier already
        # wired for term extraction; no new model config). Reuses the exact
        # same downstream handlers as the regex path, so all their
        # guardrails (real-value validation, orphan quantity cleanup,
        # single rule-loop pass) apply identically.
        _llm_intent, _ci_it, _ci_ot = _llm_classify_change_intent(
            req.question, attrs, session, req.workspace_id)
        if _llm_intent:
            _llm_attr = next(
                (a for a in attrs if a.variable_name == _llm_intent["variable_name"]), None)
            if _llm_attr is not None:
                if _llm_intent["intent"] == "remove":
                    _current = session.filled_multi.get(_llm_attr.variable_name) or []
                    _mentioned = _cpq_engine.apply_multi_answer(_llm_attr, _llm_intent["value"])
                    _to_remove = [iv for iv, _dn in _mentioned if iv in _current]
                    if _to_remove:
                        return _with_classify_usage(
                            _handle_multi_select_removal(
                                req, session, attrs, _llm_attr, _to_remove,
                                hiding_rules, rec_rules, con_rules,
                            ),
                            _ci_it, _ci_ot,
                        )
                elif _llm_intent["intent"] == "change":
                    if not _llm_intent["value"]:
                        # 2026-07-28 fix: the LLM correctly named the
                        # attribute ("change the hardware type" -> the
                        # Hardware Version attr — a match the regex label-
                        # mention check below can't see, since "hardware
                        # type" doesn't literally contain "version") but
                        # had nothing to set it to. Previously discarded
                        # entirely (_validate required a nonempty value
                        # for every intent) — the correctly-identified
                        # target attr was silently thrown away instead of
                        # asking which value, the same live-verified gap
                        # detect_change_target_without_value already fixes
                        # for its own regex-matched targets.
                        return _with_classify_usage(
                            _build_no_value_response(
                                req, session, attrs, _llm_attr, con_rules, bml_eval,
                                "cpq_llm_change_target_no_value",
                            ),
                            _ci_it, _ci_ot,
                        )
                    return _with_classify_usage(_handle_cascade(
                        req, session, attrs, _llm_attr, _llm_intent["value"],
                        hiding_rules, rec_rules, con_rules,
                    ), _ci_it, _ci_ot)

        # Recognized change-verb naming an already-filled attr, but no
        # resolvable new value ("change hardware version", "change product")
        # — ask which value instead of falling through to the generic
        # nudge below (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related
        # finding 1 — confirmed live this is the actual STEP 6 block
        # exercised once status is awaiting_approval/post_approval; a
        # first fix attempt only wired this into the SEPARATE mid-config
        # block below STEP 7, which this message never reaches).
        _no_value_attr = _cpq_engine.detect_change_target_without_value(
            req.question, attrs, session.filled,
        )
        if _no_value_attr:
            return _build_no_value_response(
                req, session, attrs, _no_value_attr, con_rules, bml_eval,
                "cpq_change_target_no_value",
            )

        # Could not parse as approval, Q&A, change, or JSON request — nudge
        # with the verbose summary, NOT the raw JSON (§6/Phase K: JSON stays
        # on-demand only; misreading input isn't a request for it).
        rule_ids_nudge = _cpq_engine.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
        summary = _cpq_summary_text(
            session.display_filled, attrs, rule_ids_nudge,
            session.product_name, req.workspace_id, sources=session.filled_source,
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

    # ── Label collision: shared display_label across 2+ distinct attrs must
    # be disambiguated, never silently resolved (docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 2). Checked before the options-query fast path below. ─────────────
    _collision = _cpq_engine.detect_label_collision(req.question, attrs)
    if _collision:
        _collision = _narrow_label_collision(req.question, _collision)
        _lines = "\n".join(
            f"- **{a.variable_name}**"
            f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
            for a in _collision
        )
        answer = (
            f"There are {len(_collision)} different attributes labeled "
            f"**\"{_collision[0].display_label}\"** in this catalog — which one "
            f"did you mean?\n\n{_lines}"
        )
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_label_collision()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # ── Attribute option query: "what values are available for X?" ────────────
    queried_attr = _cpq_engine.detect_attr_query(req.question, attrs)
    if queried_attr:
        # Constrain to values compatible with what's already selected — same
        # apply_constraint_rules call the pending-question flow already
        # makes, just missing here (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md
        # Related finding 2 — confirmed live: querying "Product" after
        # Hardware Version was set listed all 325 catalog codes instead of
        # the 2 the active constraint rule actually allows).
        _queried_constrained = _cpq_engine.apply_constraint_rules(
            attrs, con_rules, session.filled, bml_eval)
        options_block = _cpq_engine.next_question_prompt(
            queried_attr,
            constrained_item_values=_queried_constrained.get(queried_attr.entity_id),
        )
        current_val = session.filled.get(queried_attr.variable_name)
        current_note = (
            f"\n\n*Currently set to: **{session.display_filled.get(queried_attr.variable_name, current_val)}***"
            if current_val else ""
        )
        answer = (
            f"Here are the available values for "
            f"**{_cpq_engine.disambiguated_label(queried_attr, attrs)}**:"
            f"\n\n{options_block}{current_note}"
            f"\n\nReply with your choice and I'll update the configuration."
        )
        other_pending = [v for v in session.pending_variables if v != queried_attr.variable_name]
        session.pending_variables = [queried_attr.variable_name] + other_pending
        session.last_qa_variable = queried_attr.variable_name
        _persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [queried_attr.variable_name],
            "tools_called": [f"cpq_attr_query({queried_attr.variable_name})"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # ── Free-text constraint query: "what values are available for X?" asked
    # about the CURRENTLY PENDING attr when it has no options at all
    # (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md Amendment 20 follow-up).
    # detect_attr_query above can't help here (nothing to list) and its own
    # word-overlap fallback often can't even resolve a natural paraphrase
    # ("domain id" vs agencyDomainName_ID_swSoln) — but the pending attr is
    # already known, so no attr-matching is needed. Only answers when a
    # ValidationRule's script matches a describable idiom; never guesses.
    if (
        session.pending_variables and not mode_request
        and any(kw in req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)
    ):
        _pending_attr_for_constraint = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if _pending_attr_for_constraint and not _pending_attr_for_constraint.options:
            _constraint_desc = _cpq_engine.describe_free_text_constraint(
                _pending_attr_for_constraint, validation_rules,
            )
            if _constraint_desc:
                answer = (
                    f"**{_cpq_engine.disambiguated_label(_pending_attr_for_constraint, attrs)}** "
                    f"doesn't have a fixed list of values — it's free text, but it must "
                    f"only contain {_constraint_desc}."
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [_pending_attr_for_constraint.variable_name],
                    "tools_called": ["cpq_free_text_constraint()"],
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

    # Pending SYSTEM-INITIATED next-question collision — a prior turn's own
    # "what do we ask next" step (_label_collision_for) found the engine's
    # auto-picked pending[0] label-collided with another attr and asked
    # which one was meant, instead of silently guessing (live-verified
    # regression fix, 2026-07-26). Checked here, before STEP 5's normal
    # pending-answer handling, else this reply is misread as an (invalid)
    # answer to the WRONG, still-first-in-order colliding attr — confirmed
    # live: an earlier version of this check lived only inside the
    # awaiting_approval/post_approval branch above and never ran during
    # normal mid-configuration turns, so it was dead code for this exact
    # case. Same resolution shape as the pre-existing Q&A/change-request
    # collision paths: deterministic first (exact variable_name or 1-based
    # index), LLM fallback only for looser phrasing.
    if session.pending_label_collision_vns and not session.pending_label_collision_question:
        _pqc_reply = req.question.strip()
        _pqc_resolved_vn = None
        if _pqc_reply in session.pending_label_collision_vns:
            _pqc_resolved_vn = _pqc_reply
        elif _pqc_reply.isdigit():
            _pqc_idx = int(_pqc_reply) - 1
            if 0 <= _pqc_idx < len(session.pending_label_collision_vns):
                _pqc_resolved_vn = session.pending_label_collision_vns[_pqc_idx]
        if _pqc_resolved_vn is None:
            _pqc_candidates = [
                a for a in attrs if a.variable_name in session.pending_label_collision_vns
            ]
            if _pqc_candidates:
                _pqc_resolved_vn = _llm_resolve_label_collision(
                    _pqc_reply, _pqc_candidates, session, req.workspace_id)
        if _pqc_resolved_vn:
            _pqc_resolved_attr = next(
                (a for a in attrs if a.variable_name == _pqc_resolved_vn), None)
            session.pending_label_collision_vns = []
            if _pqc_resolved_attr is not None:
                session.pending_variables = [_pqc_resolved_attr.variable_name] + [
                    v for v in session.pending_variables if v != _pqc_resolved_attr.variable_name
                ]
                _pqc_ctx = _cpq_engine.build_context_sentence(
                    _pqc_resolved_attr, attrs, session.filled, session.display_filled,
                    hiding_rules, rec_rules,
                )
                _pqc_q_block = _cpq_engine.next_question_prompt(_pqc_resolved_attr, _pqc_ctx, None)
                _persist_cpq_history(req.workspace_id, req.question, _pqc_q_block)
                return {
                    "answer": _pqc_q_block, "terms": [],
                    "tools_called": ["cpq_pending_question_collision_resolved()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
        else:
            # Unrecognized reply — clear stale state rather than getting
            # stuck forever asking the same disambiguation prompt.
            session.pending_label_collision_vns = []

    # ── Mid-configuration change request (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md) ──
    # Change-request handling used to be wired ONLY into the awaiting_approval/
    # post_approval block above — a message like "change Is FedRamp or CCCS
    # Required to None" sent while OTHER fields were still pending fell
    # through unrecognized and was silently dropped (confirmed live,
    # Amendment 22 follow-up). Reuses the exact detectors + _handle_cascade
    # the awaiting_approval path already trusts; detect_change_request(s)
    # already require the named attr to be in session.filled, so a message
    # about the CURRENTLY PENDING (not yet answered) attr can never be
    # misdetected here — it keeps falling through to STEP 5 unchanged.
    if not mode_request:
        _mc_multi_matches = _cpq_engine.detect_change_requests_multi(
            req.question, attrs, session.filled, filled_multi=session.filled_multi)
        if len(_mc_multi_matches) >= 2:
            _scan_and_enqueue_remaining_targets(
                session, req.question, attrs,
                exclude_vns={a.variable_name for a, _ in _mc_multi_matches},
            )
            _mc_multi_result = _handle_cascade_multi(
                req, session, attrs, _mc_multi_matches,
                hiding_rules, rec_rules, con_rules,
            )
            if _mc_multi_result is not None:
                return _append_unmatched_targets_note(
                    _mc_multi_result, req.question, attrs,
                    {a.variable_name for a, _ in _mc_multi_matches},
                )
        else:
            _mc_change_result = _cpq_engine.detect_change_request(
                req.question, attrs, session.filled, filled_multi=session.filled_multi)
            if _mc_change_result:
                _mc_changed_attr, _mc_new_value_hint = _mc_change_result
                _scan_and_enqueue_remaining_targets(
                    session, req.question, attrs,
                    exclude_vns={_mc_changed_attr.variable_name},
                )
                return _append_unmatched_targets_note(
                    _handle_cascade(
                        req, session, attrs, _mc_changed_attr, _mc_new_value_hint,
                        hiding_rules, rec_rules, con_rules,
                    ),
                    req.question, attrs, {_mc_changed_attr.variable_name},
                )
            # Recognized change-verb naming an already-filled attr, but no
            # resolvable new value ("change hardware version") — ask which
            # value; also enqueues sibling targets on the intent queue.
            _mc_attr_no_value = _cpq_engine.detect_change_target_without_value(
                req.question, attrs, session.filled,
            )
            if _mc_attr_no_value:
                _mc_nv_result = _build_no_value_response(
                    req, session, attrs, _mc_attr_no_value, con_rules, bml_eval,
                    "cpq_change_target_no_value",
                )
                _persist_cpq_history(req.workspace_id, req.question, _mc_nv_result["answer"])
                return _mc_nv_result

    # ── STEP 5: Lock user's answer from previous turn ────────────────────────
    # pending_var must be bound regardless of whether this branch runs — the
    # STEP 5 convergence block later in this turn (clear_queue_vn) references
    # it unconditionally. None on a fresh/first-turn message (nothing was
    # pending yet) is the correct, intended value — clear_queue_vn already
    # no-ops on None.
    pending_var: str | None = None
    if session.pending_variables and session.turn > 1 and not mode_request:
        pending_var = session.pending_variables[0]
        pending_attr = next(
            (a for a in attrs if a.variable_name == pending_var), None,
        )
        # Live-verified gap (2026-07-28): once an attr with no confident
        # deterministic value got "stuck" pending (e.g. Product's 325
        # options — no exact free-text match ever resolves it), EVERY
        # subsequent message was blindly tried as an ANSWER to that same
        # question — even an obviously distinct new request like "change
        # the solution Type" (an explicit change verb naming a completely
        # different attr's own label). This trapped the customer in an
        # endless "I didn't recognise that as a valid choice for Product"
        # loop with no way to ask about anything else. Detected BEFORE
        # attempting apply_answer: if the message has a change verb AND
        # deterministically names some OTHER real attr (never the
        # currently-pending one), treat it as a genuine new request and
        # skip locking it as an answer here entirely — falls through to
        # the mid-config change-request block below, which already
        # handles a fresh "change X" during a configuring-status turn
        # (the same block that resolved "change the solution Type"
        # correctly once Product wasn't blocking it).
        _looks_like_new_request = _pending_reply_looks_like_new_request(
            req.question, pending_attr, attrs, session.filled, session.filled_multi,
        )
        if pending_attr and not _looks_like_new_request:
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
            # PROMPT 7: if we previously showed a durable scope for this
            # attr, force matching into that candidate set (never widen to
            # the full 325-option Product list on a typo/mismatch).
            _scope_cands = list(session.pending_scope_candidates or [])
            _scope_for_attr = (
                bool(_scope_cands)
                and (
                    not session.pending_scope_attr_vn
                    or session.pending_scope_attr_vn == pending_var
                )
            )
            if _scope_for_attr and pending_constrained is None:
                # Reconstruct constrained item_values from stored candidates
                # (display names and/or item_values).
                _scope_ivs: list[str] = []
                for o in pending_attr.options or []:
                    if (
                        o.item_value in _scope_cands
                        or o.display_name in _scope_cands
                    ):
                        _scope_ivs.append(o.item_value)
                if _scope_ivs:
                    pending_constrained = _scope_ivs
            elif _scope_for_attr and pending_constrained is not None:
                # Intersect recomputed constraints with remembered scope
                _scope_ivs = []
                for o in pending_attr.options or []:
                    if o.item_value not in pending_constrained:
                        continue
                    if (
                        o.item_value in _scope_cands
                        or o.display_name in _scope_cands
                    ):
                        _scope_ivs.append(o.item_value)
                if _scope_ivs:
                    pending_constrained = _scope_ivs

            # In-scope resolve ladder (exact → partial → fuzzy) before
            # unconstrained free-text / LLM — preserves "Federal" partial
            # and recovers "r7ex" within the same list.
            _scope_match_text = req.question
            if _scope_for_attr and pending_attr.select_type != "multi":
                _sres = resolve_against_scope(req.question, _scope_cands)
                if _sres.matched:
                    _scope_match_text = _sres.matched
                    logger.info(
                        "cpq_scope_match tier=%s attr=%s match=%r run_id=%s",
                        _sres.tier, pending_var, _sres.matched,
                        session.run_id or "-",
                    )

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
                result = _cpq_engine.apply_answer(
                    pending_attr, _scope_match_text, pending_constrained)
                if not result and _scope_match_text != req.question:
                    result = _cpq_engine.apply_answer(
                        pending_attr, req.question, pending_constrained)
                if not result and hint_val_for_attr:
                    result = _cpq_engine.apply_answer(
                        pending_attr, hint_val_for_attr, pending_constrained)
            # Gap A (Amendment 2): fragment-match found nothing — try the
            # shared Tier-2 LLM fallback before giving up, scoped to only
            # this attr's own options. Single-select only: apply_multi_answer
            # already scans for multiple named options, so a multi-select
            # miss is a genuine no-match, not a long-sentence problem.
            _llm_low_confidence_candidates = None
            if not result and pending_attr.select_type != "multi":
                _llm_pick = _llm_resolve_pending_answer(req.question, pending_attr, req.workspace_id)
                if _llm_pick and _llm_pick["confidence"] == "high":
                    # Only accept LLM pick if it stays inside active scope
                    _iv = _llm_pick["iv"]
                    if (
                        pending_constrained is None
                        or _iv in pending_constrained
                    ):
                        result = (_llm_pick["iv"], _llm_pick["disp"])
                elif _llm_pick and _llm_pick["confidence"] == "low":
                    _cands = _llm_pick["candidates"]
                    if pending_constrained is not None:
                        _allowed_disp = {
                            o.display_name for o in pending_attr.options
                            if o.item_value in pending_constrained
                        }
                        _cands = [c for c in _cands if c in _allowed_disp]
                    _llm_low_confidence_candidates = _cands or None
            if result:
                clear_pending_scope(session)
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
                    # Amendment 12 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
                    # PLAN.md): a catalog-authored warning-message rule
                    # (e.g. CommandCentral Aware's "Constrain video
                    # devices" — device count must be a multiple of 25)
                    # must not be silently accepted just because the value
                    # fragment-matched — same "never guess/never silently
                    # accept a flagged value" discipline as everywhere
                    # else in this engine. Checked against the FULL
                    # filled state including this new answer.
                    _validation_warnings = _cpq_engine.apply_validation_rules(
                        attrs, session.filled, validation_rules, bml_eval=bml_eval)
                    _warning_msg = _validation_warnings.get(pending_var)
                    if _warning_msg:
                        del session.filled[pending_var]
                        session.display_filled.pop(pending_var, None)
                        session.filled_source.pop(pending_var, None)
                        _opts_prompt = _cpq_engine.next_question_prompt(pending_attr)
                        _validation_answer = f"⚠️ {_warning_msg}\n\n{_opts_prompt}"
                        _persist_cpq_history(req.workspace_id, req.question, _validation_answer)
                        return {
                            "answer": _validation_answer, "terms": [],
                            "tools_called": ["cpq_validation_warning()"],
                            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                        }
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
            elif _llm_low_confidence_candidates:
                # Gap A confidence gating (Amendment 2): the LLM fallback
                # found 2+ real, valid options it could plausibly mean —
                # a judgment call between real options, not hallucination,
                # so it must not silently commit (same "never guess a real
                # decision" discipline as an ambiguous label collision).
                _pending_label = _cpq_engine.disambiguated_label(pending_attr, attrs)
                set_pending_scope(
                    session,
                    kind="attr_options",
                    candidates=list(_llm_low_confidence_candidates),
                    origin_question=req.question,
                    attr_vn=pending_var,
                    asked_turn=session.turn,
                )
                _lines = "\n".join(f"- {c}" for c in _llm_low_confidence_candidates)
                _static_answer = (
                    f"I'm not certain which option you meant for "
                    f"**{_pending_label}** — could you confirm which one?\n\n{_lines}"
                )
                answer = _compose_disambiguation_question(
                    req.question, f"which value they meant for {_pending_label}",
                    _llm_low_confidence_candidates,
                    {"Country": session.country, "Product": session.product_name},
                    _static_answer, req.workspace_id,
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_low_confidence_answer()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
            elif pending_attr.options:
                # Answer matched nothing — SCOPED re-ask (PROMPT 7).
                # Never fall through to next_question_prompt without
                # constrained_item_values: that dumped the full 325-option
                # Product list after a constrained family list (live: r7ex).
                _pending_label = _cpq_engine.disambiguated_label(pending_attr, attrs)
                if not session.pending_scope_candidates or (
                    session.pending_scope_attr_vn
                    and session.pending_scope_attr_vn != pending_var
                ):
                    # First miss without a remembered scope — capture the
                    # constrained set we just matched against.
                    _remember_attr_scope(
                        session, pending_attr, pending_constrained, req.question,
                    )
                if session.pending_scope_candidates:
                    return _scoped_reask_response(
                        req, session, req.question,
                        scope_label=_pending_label,
                        tools_called="cpq_invalid_answer()",
                    )
                # Structurally unexpected: options exist but no scope and
                # no constraints — last resort constrained re-prompt.
                log_scope_lost(
                    run_id=session.run_id or "",
                    reply=req.question,
                    reason="invalid_answer_no_scope",
                )
                opts_prompt = _cpq_engine.next_question_prompt(
                    pending_attr, "", pending_constrained,
                )
                _remember_attr_scope(
                    session, pending_attr, pending_constrained, req.question,
                )
                answer = (
                    f"I didn't recognise **\"{req.question.strip()}\"** as a valid "
                    f"choice for **{_pending_label}**. Please pick one:\n\n{opts_prompt}"
                )
                _persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [], "tools_called": ["cpq_invalid_answer()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }

    # ── STEP 5b: removal while blocked with no pending question ──────────────
    # `session.pending_variables` is empty whenever the previous turn ended
    # on unresolved_grid_quantity_options' block (a selected grid option has
    # no resolvable per-row quantity attr — e.g. SVX's bare "Magnetic Mount")
    # rather than on a genuine next question, so STEP 5 above never fires and
    # the turn fell straight to STEP 3 with filled_multi unchanged, re-hitting
    # the identical block. Live-verified bug (2026-07-22): "okay remove it"
    # was silently discarded this way — the block even told the user to
    # "remove it" but nothing ever tried to parse that as a removal. Tried
    # here, before STEP 3 re-runs the loop and re-emits the same warning.
    if not session.pending_variables and session.turn > 1 and not mode_request:
        _gap_removal_match = _cpq_engine.detect_multi_select_removal(
            req.question, attrs, session.filled_multi)
        if _gap_removal_match:
            _gap_attr, _gap_to_remove = _gap_removal_match
            return _handle_multi_select_removal(
                req, session, attrs, _gap_attr, _gap_to_remove,
                hiding_rules, rec_rules, con_rules,
            )
        # The block's own wording says "remove it" — a pronoun, not a named
        # option, so detect_multi_select_removal (which requires the option
        # to actually be named) never matches it. When the message still
        # carries a removal verb and there's exactly one unresolved gap
        # option, resolve "it" to that one unambiguous gap directly.
        elif _cpq_engine._REMOVE_VERB_RE.search(req.question):
            _by_vn = {a.variable_name: a for a in attrs}
            _grid_links = _cpq_engine.resolve_array_grid_links(attrs)
            _gaps = [
                (selector_vn, item_value)
                for selector_vn, item_map in _grid_links.items()
                for item_value in (session.filled_multi.get(selector_vn) or [])
                if item_value.strip().lower() not in item_map
            ]
            if len(_gaps) == 1:
                _gap_selector_vn, _gap_item_value = _gaps[0]
                _gap_attr = _by_vn.get(_gap_selector_vn)
                if _gap_attr is not None:
                    return _handle_multi_select_removal(
                        req, session, attrs, _gap_attr, [_gap_item_value],
                        hiding_rules, rec_rules, con_rules,
                    )

    # ── STEP 3: Rule evaluation loop (hide → recommend → constrain) ──────────
    prev_filled_snapshot = dict(session.filled)
    # Also snapshotted for dropped_note's wording below — distinguishes a
    # value the SESSION already held before this turn (a real prior
    # answer, now invalidated by whatever this turn changed) from one
    # evaluate_rules_loop's own internal iteration filled AND discarded
    # within this SAME turn (turn 1's settling churn, before the
    # customer ever gave any input at all — confirmed live: a fresh
    # "Quote SVX..." turn 1 showed 3 single-select attrs "Removed ... —
    # no longer valid after this change" despite session.filled starting
    # completely empty that turn).
    prev_filled_multi_snapshot = {k: list(v) for k, v in session.filled_multi.items()}
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    # once _bm_model_variable_name was resolved via the model-leaf
    # disambiguation above (proving this catalog's real identity travels
    # through the bm_catalog tree, not any "Product"-labeled attr), every
    # attr sharing that display_label is proven irrelevant/generic for
    # this catalog (Amendment 5 Finding 3) — skip asking for them, same
    # mechanism the pre-existing model/product mutual-exclusivity logic
    # already uses for the single-leaf case (resolve_always_ask_skips).
    # Gated on model_leaf_resolved specifically (not merely
    # "_bm_model_variable_name is filled"), since that field could in
    # principle be set through some other, less certain path elsewhere.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    def _recompute_pending(cur_hints):
        """One evaluate_rules_loop + auto_fill + post-filter pass, over
        whatever `cur_hints` currently holds. Factored out so Amendment 17
        below can re-run the exact same pass a second time after enriching
        `hints` with LLM-extracted facts, without duplicating this block or
        risking it drift out of sync with the normal (Tier-1-only) path."""
        v_attrs, f, d_filled, c_opts = _cpq_engine.evaluate_rules_loop(
            attrs, cur_hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
            bml_eval=bml_eval, filled_source=session.filled_source,
            filled_multi=session.filled_multi, dropped_multi=dropped_multi,
            country=session.country, negated_vns=negated_vns,
            skip_always_ask=skip_always_ask,
        )
        g_ids = _cpq_engine.governed_target_ids(v_attrs, hiding_rules, rec_rules, con_rules)
        r_ids = _cpq_engine.rule_governed_ids(v_attrs, hiding_rules, rec_rules, con_rules)
        _, _, p = _cpq_engine.auto_fill(
            v_attrs, cur_hints, already_filled=f, constrained_opts=c_opts,
            governed_ids=g_ids, already_filled_multi=session.filled_multi,
            dropped_multi=dropped_multi, rule_governed_ids=r_ids, country=session.country,
            negated_vns=negated_vns, filled_source=session.filled_source,
            skip_always_ask=skip_always_ask, bml_eval=bml_eval,
            validation_rules=validation_rules,
            )
        if session.model_leaf_resolved:
            # skip_always_ask only suppresses the always-ask OVERRIDE — it
            # doesn't stop a genuinely required, no-default attr from staying
            # "pending" with nothing to fall back to. Since the resolved
            # model-leaf identity already proves these "Product"-labeled attrs
            # are irrelevant to THIS catalog's real flow (Amendment 5 Finding
            # 3), drop them from `pending` outright rather than asking for
            # them at all — they're already excluded from the payload above.
            p = [
                a for a in p
                if a.variable_name not in _cpq_engine.product_label_noise_vns(
                    v_attrs, hiding_rules, rec_rules, con_rules)
            ]
        _gq_vns = {a.variable_name for a in p}
        for _qty_attr in _cpq_engine.resolve_pending_grid_quantities(
                v_attrs, f, session.filled_multi):
            if _qty_attr.variable_name not in _gq_vns:
                p.append(_qty_attr)
                _gq_vns.add(_qty_attr.variable_name)
        return v_attrs, f, d_filled, p, c_opts, r_ids

    visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids = (
        _recompute_pending(hints))

    # Amendment 17 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): Tier-1's
    # fragment matching can correctly, deliberately leave 2+ attrs
    # unresolved on one dense sentence — it never guesses a value two
    # sibling attrs both accept (e.g. devices vs. locations both taking
    # "25"), and it skips single-word values as unsafe (see
    # extract_catalog_hints' own docstring). That leaves a human-obvious
    # multi-fact sentence to be asked back one attr at a time — give the
    # shared Tier-2 classifier one shot at the ones this sentence
    # genuinely seems to mention before falling back to that. Gated on a
    # GENUINE multi-mention overlap (fallback_to_full=False) so this never
    # fires on an ordinary short reply where nothing textually overlaps.
    if len(pending) >= 2:
        _multi_candidates = _relevant_intent_candidates(
            req.question, pending, fallback_to_full=False)
        if len(_multi_candidates) >= 2:
            _extra_hints = _llm_extract_multi_attr_hints(
                req.question, _multi_candidates, req.workspace_id)
            if _extra_hints:
                for _vn, _iv in _extra_hints.items():
                    hints.setdefault(_vn, _iv)
                visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids = (
                    _recompute_pending(hints))

    def _dropped_phrase(dvar: str, dvals: list[str]) -> str:
        label = next((a.display_label for a in attrs if a.variable_name == dvar), dvar)
        had_prior_value = dvar in prev_filled_snapshot or bool(prev_filled_multi_snapshot.get(dvar))
        if had_prior_value:
            # A real prior value (this session already held it before
            # this turn started) genuinely got invalidated by whatever
            # this turn changed — the customer-facing "after this
            # change" framing is accurate here.
            return (
                f" Removed **{', '.join(dvals)}** from **{label}** "
                f"— no longer valid after this change."
            )
        # evaluate_rules_loop's own internal settling filled AND
        # discarded this within the SAME turn — never a value the
        # customer (or a prior turn) ever actually held, so "after this
        # change" would misleadingly imply a customer action caused it.
        return f" **{label}** doesn't currently offer **{', '.join(dvals)}** as a valid option."

    dropped_note = "".join(
        _dropped_phrase(dvar, dvals) for dvar, dvals in dropped_multi.items()
    )
    if dropped_note:
        # Suppressed from the customer-facing response by explicit
        # product decision — the mechanism itself is correct (see
        # _dropped_phrase's had_prior_value distinction, live-verified
        # earlier this session), but surfacing "Removed X from Y" text
        # directly in the summary reads as noisy/technical to the
        # customer. Logged instead so the cascade is still auditable.
        logger.info(
            "cpq_cascade_dropped_note (suppressed from customer response): "
            "%s [run_id=%s]", dropped_note.strip(), session.run_id or "-",
        )
        dropped_note = ""

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

    # Multi-target intent queue drain (STEP 5 convergence): the attr just
    # answered is `pending_var` (captured at lock time). Clear it from the
    # queue, then force the next queue head to the front of pending.
    clear_queue_vn(session, pending_var)
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)

    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    if not pending and unresolved_grid_gaps:
        # A selected grid option has NO resolvable quantity attr at all
        # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9) — never silently
        # complete with a permanent per-row gap; block and ask the
        # customer to resolve it (remove the selection or pick another).
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            (f"{dropped_note.strip()}\n\n" if dropped_note else "")
            + f"⚠️ {gap_list} has no quantity field configured in this "
              f"catalog. Please remove it or choose a different option "
              f"before this configuration can be completed."
        )
    elif not pending:
        # ── STEP 6: FORMAT B — verbose summary, JSON only on request ─────────
        # (§6/Phase K: JSON is never shown unasked, even at completion —
        # only the earlier "still configuring" responses honored this
        # before; this branch previously dumped the full BOM immediately.)
        session.status = "awaiting_approval"
        summary = _cpq_summary_text(
            display_filled, visible_attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
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
        _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            q_block = _cpq_engine.next_question_prompt(
                next_attr, "", constrained_opts.get(next_attr.entity_id),
                validation_rules=validation_rules,
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
                session.product_name, req.workspace_id, sources=session.filled_source,
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
                    a, ctx, constrained_opts.get(a.entity_id),
                    validation_rules=validation_rules))
            answer = (
                (f"{dropped_note.strip()}\n\n" if dropped_note else "")
                + f"Here's everything still needed ({len(pending)} item(s)):\n\n"
                + "\n\n---\n\n".join(blocks)
            )
        else:
            # ── STEP 4: FORMAT A — context sentence + numbered options only ──
            next_attr = pending[0]
            _pending_collision = _label_collision_for(next_attr, visible_attrs, session)
            if _pending_collision:
                session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
                answer = dropped_note + _label_collision_prompt(
                    _pending_collision, session, req.question, req.workspace_id)
            else:
                context_sentence = dropped_note + _cpq_engine.build_context_sentence(
                    next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
                )
                constrained_vals = constrained_opts.get(next_attr.entity_id)
                # FORMAT A: pure options prompt — no background state, no counters
                answer = _cpq_engine.next_question_prompt(
                    next_attr, context_sentence, constrained_vals,
                    validation_rules=validation_rules,
                )
                # PROMPT 7: remember the exact option list shown so a typo
                # on the next turn re-asks within this scope (never 325).
                _remember_attr_scope(
                    session, next_attr, constrained_vals, req.question,
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


def _standard_ask_pipeline(req: AskRequest, reader: Any) -> dict[str, Any]:
    """Non-CPQ Ask: term extraction → graph retrieval → synthesis."""
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


def _finish_cpq_result(
    result: dict[str, Any] | None,
    req: AskRequest,
    reader: Any,
    *,
    route_meta: AskRouteDecision | None = None,
) -> dict[str, Any] | None:
    """Attach share flags + bidirectional shadow logs; return result or None."""
    if not result:
        return None
    try:
        logger.info(
            "cpq_shadow_intent_actual: tools_called=%s status=%s",
            result.get("tools_called"),
            (result.get("session_data") or {}).get("status"),
        )
        if route_meta is not None:
            logger.info(
                "cpq_router: model_id=%s llm_route=%s det_is_cpq=%s agreement=%s "
                "confidence=%s timed_out=%s error=%r tokens=(%d,%d)",
                route_meta.model_id, route_meta.route, route_meta.det_is_cpq,
                route_meta.agreement, route_meta.confidence,
                route_meta.timed_out, route_meta.error,
                route_meta.prompt_tokens, route_meta.completion_tokens,
            )
    except Exception:  # noqa: BLE001
        logger.debug("cpq_shadow_intent_actual: logging failed", exc_info=True)
    _attach_share_flags(result, req, reader)
    return result


def _deterministic_cpq_gate(req: AskRequest, reader: Any) -> bool:
    """Legacy auditor: regex/alias only — NO second LLM classification call.

    Demoted from primary router to post-check / escape-hatch path so the
    turn pays at most one gateway LLM call (Prompt 3 acceptance).
    """
    if req.session_data.get("mode") == "cpq":
        return True
    return bool(
        _cpq_engine.is_cpq_question(req.question, reader, req.workspace_id)
    )


def _route_quote(
    req: AskRequest, reader: Any, meta: AskRouteDecision | None = None,
) -> dict[str, Any]:
    result = _run_cpq_turn(req, reader)
    finished = _finish_cpq_result(result, req, reader, route_meta=meta)
    if finished:
        return finished
    # No CPQ graph data — fall through to standard Ask rather than empty.
    return _standard_ask_pipeline(req, reader)


def _route_qa(
    req: AskRequest, reader: Any, meta: AskRouteDecision | None = None,
) -> dict[str, Any]:
    """QA path — handlers execute only; no re-classification.

    N2 harden: cold-start QA loads catalog attrs via a *read-only* product
    mention resolve for option lists — never writes session.product_name
    or triggers a family switch (few-shot: 'options for product' must not
    hop to softwareSolutions_BOM).
    """
    session = (
        CpqSession.from_dict(req.session_data)
        if req.session_data.get("mode") == "cpq"
        else CpqSession()
    )
    if not session.run_id:
        session.run_id = uuid.uuid4().hex
    set_run_id(session.run_id)
    attrs: list = []
    product_for_attrs = session.product_name
    if not product_for_attrs:
        # Read-only resolve — do NOT assign session.product_name (N2/N3).
        try:
            _hints = _cpq_engine.extract_hints(req.question)
            mentioned = _cpq_engine.detect_product_mention(
                req.question, _hints, reader, req.workspace_id,
            )
            if mentioned:
                product_for_attrs = mentioned
                logger.info(
                    "route_qa: read_only product context=%r (session.product_name unchanged)",
                    mentioned,
                )
        except Exception:  # noqa: BLE001
            logger.debug("route_qa: detect_product_mention failed", exc_info=True)
    if product_for_attrs:
        try:
            attrs, _ = _cpq_engine.load_product_config(
                reader, req.workspace_id, product_for_attrs,
            )
        except Exception:  # noqa: BLE001
            logger.debug("route_qa: load_product_config failed", exc_info=True)
            attrs = []
    result = _handle_cpq_qa(req, session, attrs, reader, resume_review=False)
    # Belt-and-suspenders: never let QA path mutate product without switch.
    if result and isinstance(result.get("session_data"), dict):
        if req.session_data.get("mode") != "cpq":
            # Cold QA shell — strip product commits if any leaked.
            sd = dict(result["session_data"])
            if not req.session_data.get("product_name"):
                if sd.get("product_name") and sd.get("status") not in (
                    "awaiting_approval", "post_approval", "configuring",
                ):
                    pass  # allow only if engine already entered real CPQ
            result["session_data"] = sd
    finished = _finish_cpq_result(result, req, reader, route_meta=meta)
    return finished or _standard_ask_pipeline(req, reader)


def _route_ambiguous(meta: AskRouteDecision, req: AskRequest) -> dict[str, Any]:
    cq = meta.clarifying_question or (
        "Are you looking to configure or quote a product, or ask a "
        "general product question?"
    )
    return {
        "answer": cq,
        "terms": [],
        "tools_called": ["cpq_ask_route_ambiguous()"],
        "usage": {
            "prompt_tokens": meta.prompt_tokens,
            "completion_tokens": meta.completion_tokens,
            "latency_ms": 0,
            "menial_model": meta.model_id or "cpq-intent-gateway",
            "answer_model": meta.model_id or "cpq-intent-gateway",
        },
        "grounding": None,
        "session_data": req.session_data or {},
        "cpq_payload": None,
    }


def run_ask(req: AskRequest) -> dict[str, Any]:
    """Execute the Aryx Ask pipeline for a request payload.

    Prompt 3 — inverted router (config-reversible):
      ARYX_CPQ_INTENT_MODE=
        llm_first          — gateway routes every cold-start turn
        deterministic_first — legacy is_cpq_question gate only
        shadow (default)   — deterministic decides; gateway logs agreement

    Live CPQ sessions always enter _run_cpq_turn (session owns state).
    BOM payloads still only come from auto_fill → rule loop → build_payload.
    """
    reader = _reader(req.workspace_id)
    settings = get_settings()
    mode = (settings.cpq_intent_mode or "shadow").strip().lower()
    live_session = req.session_data.get("mode") == "cpq"

    # ── Live session: always CPQ turn (engine owns switch/undo/cascade) ─────
    # N3: switch confirmation stays inside _run_cpq_turn — log explicit hint.
    if live_session:
        logger.info(
            "cpq_router: live_session product=%r status=%r — skip top-level route",
            req.session_data.get("product_name"),
            req.session_data.get("status"),
        )
        return _route_quote(req, reader)

    # N10: hard off-topic before any mode work (no LLM, no CPQ).
    if hard_off_topic(req.question):
        logger.info("cpq_router: hard_off_topic → standard Ask")
        return _standard_ask_pipeline(req, reader)

    det_is_cpq = _deterministic_cpq_gate(req, reader)
    soft_quote = soft_quote_heuristic(req.question)

    # ── deterministic_first: legacy short-circuit (no gateway LLM) ──────────
    if mode == "deterministic_first":
        is_cpq = (
            det_is_cpq
            or soft_quote
            or _llm_classify_is_cpq_question(req.question, req.workspace_id)
        )
        if is_cpq:
            return _route_quote(req, reader)
        return _standard_ask_pipeline(req, reader)

    # ── llm_first / shadow: one top-level gateway call ──────────────────────
    route_meta = classify_ask_route(
        req.question,
        workspace_id=req.workspace_id,
        session_hint="none (cold start)",
        det_is_cpq=det_is_cpq,
        timeout_s=float(settings.cpq_intent_timeout_s or 10.0),
    )
    # N4: mid-session gateway in _run_cpq_turn will no-op this turn.
    mark_top_level_route_used()

    # Escape hatch: timeout / double validation / transport error → det path
    # N6: soft_quote catches "order APX…" paraphrases det regex misses.
    if route_meta.error or route_meta.timed_out:
        logger.warning(
            "cpq_router: escape_hatch mode=%s error=%r timed_out=%s "
            "det=%s soft_quote=%s → fallback",
            mode, route_meta.error, route_meta.timed_out, det_is_cpq, soft_quote,
        )
        if det_is_cpq or soft_quote:
            return _route_quote(req, reader, route_meta)
        return _standard_ask_pipeline(req, reader)

    # Bidirectional shadow log (LLM route + det auditor)
    log_fn = logger.warning if (
        mode == "shadow" and route_meta.agreement is False
    ) else logger.info
    # N5: shadow disagreements are WARNING-level so they show in ops filters.
    log_fn(
        "cpq_router_shadow: mode=%s llm_route=%s det_is_cpq=%s agreement=%s "
        "soft_quote=%s model_id=%s rationale=%r",
        mode, route_meta.route, det_is_cpq, route_meta.agreement,
        soft_quote, route_meta.model_id, route_meta.rationale,
    )

    if mode == "shadow":
        # Deterministic path still decides; gateway is observe-only.
        # N6: soft_quote widens det path so shadow traffic mirrors escape hatch.
        if det_is_cpq or soft_quote:
            return _route_quote(req, reader, route_meta)
        return _standard_ask_pipeline(req, reader)

    # ── llm_first: handlers execute the gateway decision ────────────────────
    if route_meta.route == "off_topic":
        return _standard_ask_pipeline(req, reader)

    if route_meta.route == "quote":
        if det_is_cpq is False:
            logger.info(
                "cpq_router: llm_first quote with det_is_cpq=False "
                "(auditor disagreement — proceeding with LLM)",
            )
        return _route_quote(req, reader, route_meta)

    if route_meta.route == "qa":
        return _route_qa(req, reader, route_meta)

    if route_meta.route == "ambiguous":
        return _route_ambiguous(route_meta, req)

    return _standard_ask_pipeline(req, reader)


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
