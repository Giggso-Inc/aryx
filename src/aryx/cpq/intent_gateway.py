"""LLM-first intent gateway with quarantine guardrails.

One structured Gemini Pro call per turn (model id pinned in config).
The model only SELECTS from candidate lists built from
``CpqEngine.load_product_config`` + the current ``CpqSession`` — never
emits free-text catalog identifiers or values.

Quarantine (fail closed → AMBIGUOUS):
  - variable_name must be in the injected candidate set
  - value_ref must be in-range for that attr's value candidates
  - evidence_span must appear verbatim in the user question

Retry: 1 schema retry → clarify → fall back to deterministic flow.
Mutating intents require agreement with existing detect_* functions.
Results cached by (normalized_question, session_state_hash).

Does NOT touch auto_fill, the rule loop, or BOM payload synthesis.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor
from aryx.config import get_settings
from aryx.cpq.intent_schema import (
    GATEWAY_INTENT_JSON_SCHEMA,
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    parse_gateway_intent,
    validate_gateway_quarantine,
)
from aryx.cpq.logging_context import get_run_id
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
from aryx.cpq.telemetry import (
    DivergenceRecord,
    deterministic_category_summary,
    log_divergence,
    log_rejection,
)
from aryx.llm import complete_text

logger = logging.getLogger(__name__)

# Mutating intents — LLM + deterministic detectors must agree.
MUTATING_CATEGORIES = frozenset({
    IntentCategory.CHANGE_REQUEST,
    IntentCategory.CHANGE_TARGET_WITHOUT_VALUE,
    IntentCategory.CHANGE_REQUESTS_MULTI,
    IntentCategory.MULTI_SELECT_REMOVAL,
    IntentCategory.ATTR_CLEAR,
    IntentCategory.ATTR_ACTIVATION,
    IntentCategory.BULK_QUANTITY_CHANGE,
})

_VALUE_CAP = 40
_ATTR_CAP = 60
_WORD_RE = re.compile(r"[a-z0-9]+")

# Module-level cache: key → (GatewayIntentResult, pt, ct, model_id)
_CACHE: dict[str, tuple[GatewayIntentResult, int, int, str]] = {}
_CACHE_MAX = 256

# N4: when top-level classify_ask_route already ran this turn, skip the
# mid-session STEP-6 gateway so the turn pays one LLM classification call.
_top_level_route_used: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cpq_top_level_route_used", default=False,
)

# N10: hard off-topic veto — do not trust LLM if these fire.
_OFF_TOPIC_HARD = re.compile(
    r"\b(astrolog(?:y|ical)?|horoscope|zodiac|tarot|"
    r"weather|forecast|world\s*cup|tell\s+me\s+a\s+joke|knock[\s-]knock)\b",
    re.IGNORECASE,
)
# N6: soft quote bias for escape hatch when regex/alias miss paraphrases.
_SOFT_QUOTE = re.compile(
    r"\b(order|configure|config|quote|qty|quantity|radios?|"
    r"destination\s+country|hardware\s+version|bom|apx|svx|"
    r"command\s*central|service\s+type)\b",
    re.IGNORECASE,
)


def mark_top_level_route_used() -> None:
    """Call from run_ask after classify_ask_route — N4 one-LLM-call guard."""
    _top_level_route_used.set(True)


def top_level_route_used() -> bool:
    return bool(_top_level_route_used.get())


def soft_quote_heuristic(question: str) -> bool:
    """True when message looks like order/config even if is_cpq_question misses."""
    return bool(_SOFT_QUOTE.search(question or ""))


def hard_off_topic(question: str) -> bool:
    """N10: deterministic off-topic veto (astrology, weather, jokes, …)."""
    return bool(_OFF_TOPIC_HARD.search(question or ""))


@dataclass(frozen=True)
class ValueCandidate:
    """One selectable value the LLM may reference by index only."""

    index: int
    item_value: str
    display_name: str


@dataclass
class AttrCandidateBundle:
    """Attribute + ordered value candidates for the prompt/validator."""

    attr: ConfigAttr
    values: list[ValueCandidate]


@dataclass
class GatewayDecision:
    """Outcome of one gateway classify call for the turn orchestrator."""

    action: Literal["dispatch", "clarify", "fallback"]
    result: GatewayIntentResult | None
    # Resolved from value_ref against candidate lists in OUR code — never
    # taken as free text from the model.
    value_display: str | None = None
    value_item: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_id: str = ""
    cache_hit: bool = False
    reason: str = ""


def _normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def session_state_hash(session: CpqSession) -> str:
    """Stable fingerprint of the config state the candidates depend on."""
    payload = {
        "product": session.product_name,
        "filled": sorted(session.filled.items()),
        "filled_multi": sorted(
            (k, tuple(v)) for k, v in session.filled_multi.items()
        ),
        "pending": list(session.pending_variables[:20]),
        "pending_change_no_value": session.pending_change_no_value_vn,
        "pending_change_collision": list(session.pending_change_collision_vns),
        "pending_clarify": list(session.pending_clarify_vns),
        "status": session.status,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_key(question: str, session: CpqSession, model_id: str = "") -> str:
    # N9: isolate cache by model + worker pid so multi-worker / model
    # flips never reuse a stale classification from another process identity.
    mid = model_id or get_settings().cpq_intent_gemini_model
    return (
        f"{mid}|pid={os.getpid()}|"
        f"{_normalize_question(question)}|{session_state_hash(session)}"
    )


def build_candidate_bundles(
    attrs: list[ConfigAttr],
    session: CpqSession,
    question: str,
) -> list[AttrCandidateBundle]:
    """Build attr/value candidates from product config + session state.

    Prefers attributes that are filled, pending, or word-overlap the
    question so the prompt stays bounded on large catalogs.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    scored: list[tuple[float, ConfigAttr]] = []
    for a in attrs:
        score = 0.0
        if a.variable_name in session.filled or a.variable_name in session.filled_multi:
            score += 5.0
        if session.pending_variables and a.variable_name == session.pending_variables[0]:
            score += 8.0
        if session.last_qa_variable and a.variable_name == session.last_qa_variable:
            score += 8.0
        if a.variable_name in session.pending_change_collision_vns:
            score += 7.0
        if a.variable_name == session.pending_change_no_value_vn:
            score += 7.0
        if a.variable_name in session.pending_clarify_vns:
            score += 7.0
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        vocab |= set(_WORD_RE.findall(a.variable_name.lower().replace("_", " ")))
        for o in a.options[:_VALUE_CAP]:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        score += len(q_words & vocab)
        if score > 0 or a.required:
            scored.append((score, a))
    scored.sort(key=lambda p: p[0], reverse=True)
    chosen = [a for _s, a in scored[:_ATTR_CAP]]
    if not chosen:
        chosen = attrs[: min(20, len(attrs))]

    bundles: list[AttrCandidateBundle] = []
    for a in chosen:
        values: list[ValueCandidate] = []
        for i, o in enumerate(a.options[:_VALUE_CAP]):
            values.append(ValueCandidate(
                index=i, item_value=o.item_value, display_name=o.display_name,
            ))
        bundles.append(AttrCandidateBundle(attr=a, values=values))
    return bundles


def _format_candidates_for_prompt(bundles: list[AttrCandidateBundle],
                                  session: CpqSession) -> str:
    lines: list[str] = []
    for b in bundles:
        a = b.attr
        current = (
            session.filled_multi.get(a.variable_name)
            or session.filled.get(a.variable_name)
        )
        if b.values:
            val_lines = "; ".join(
                f"[{v.index}] {v.display_name}" for v in b.values
            )
        else:
            val_lines = "(free-text / no menu — value_ref must be null)"
        lines.append(
            f"- variable_name={a.variable_name!r} label={a.display_label!r} "
            f"type={a.select_type} current={current!r}\n"
            f"  VALUE CANDIDATES: {val_lines}"
        )
    return "\n".join(lines)


def _pinned_chat(
    system: str, user: str, model_id: str, workspace_id: int,
) -> tuple[str, int, int]:
    """One completion against the pinned intent model (Gemini Pro default)."""
    settings = get_settings()
    provider = settings.llm_provider
    is_ollama = provider == "ollama"
    registry = Registry()
    registry.add(ModelSpec(
        name=model_id,
        provider=provider,
        tier="frontier",
        local=is_ollama,
        endpoint=settings.llm_base_url or None,
        api_key_ref=None if is_ollama else "ARYX_RUNTIME_KEY",
    ))

    class _Secrets:
        def get(self, ref: str) -> str:
            return settings.llm_api_key or ""

    broker = Broker(registry, TokenGovernor({}), secrets=_Secrets())
    start = time.monotonic()
    text, pt, ct = complete_text(broker, "frontier", system, user, think=False)
    ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "cpq_intent_gateway: model=%s run_id=%s tokens=(%d,%d) latency_ms=%d",
        model_id, get_run_id() or "-", pt, ct, ms,
    )
    return text, pt, ct


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        s, e = text.find("{"), text.rfind("}")
        if s < 0 or e < 0:
            return None
        raw = json.loads(text[s:e + 1])
        return raw if isinstance(raw, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _llm_classify_once(
    question: str,
    bundles: list[AttrCandidateBundle],
    session: CpqSession,
    model_id: str,
    workspace_id: int,
    repair_hint: str = "",
) -> tuple[GatewayIntentResult | None, int, int]:
    """Single structured call; returns (parsed_or_None, pt, ct)."""
    candidate_block = _format_candidates_for_prompt(bundles, session)
    categories = ", ".join(c.value for c in IntentCategory)
    sys = (
        "You classify one user message in a product-configuration chat.\n"
        "Reply ONLY as JSON matching this schema (no markdown, no prose):\n"
        f"{json.dumps(GATEWAY_INTENT_JSON_SCHEMA, indent=1)}\n\n"
        f"Valid intent_category values: {categories}.\n"
        "HARD RULES:\n"
        "1. variable_name MUST be copied EXACTLY from CANDIDATE ATTRIBUTES "
        "or null. Never invent a field code.\n"
        "2. value_ref MUST be an integer index from that attr's VALUE "
        "CANDIDATES, or null. Never free-text values.\n"
        "3. evidence_span MUST be an exact contiguous substring of USER "
        "MESSAGE (copy-paste from the message).\n"
        "4. If unsure which attribute/value, use intent_category="
        "\"ambiguous\" with a specific clarifying_question.\n"
        "5. confidence=\"low\" means the caller will not act — prefer "
        "ambiguous when between two plausible options.\n"
    )
    if repair_hint:
        sys += f"\nPREVIOUS ATTEMPT FAILED VALIDATION: {repair_hint}\nFix the JSON.\n"

    pending_bits: list[str] = []
    if session.pending_variables:
        pending_bits.append(f"pending_attr={session.pending_variables[0]}")
    if session.pending_change_no_value_vn:
        pending_bits.append(
            f"awaiting_value_for={session.pending_change_no_value_vn}"
        )
    if session.pending_clarify_vns:
        pending_bits.append(
            "awaiting_clarify_pick="
            + "|".join(session.pending_clarify_vns[:8])
            + (
                f" (original={session.pending_clarify_question!r})"
                if session.pending_clarify_question else ""
            )
        )
    if session.last_qa_variable:
        pending_bits.append(
            f"customer_last_asked_about={session.last_qa_variable} "
            "(their immediately preceding message was a question about this "
            "attribute — a short follow-up like 'make it X' most likely "
            "refers to it, even if X is also technically a valid value for "
            "another attribute)"
        )
    pending_line = (
        "SESSION PENDING: " + ", ".join(pending_bits) + "\n"
        if pending_bits else ""
    )
    user = (
        f"{pending_line}"
        f"CANDIDATE ATTRIBUTES (select from these only):\n{candidate_block}\n\n"
        f"USER MESSAGE:\n{question}\n"
    )
    try:
        text, pt, ct = _pinned_chat(sys, user, model_id, workspace_id)
    except Exception as exc:  # noqa: BLE001 — gateway must never crash the turn
        logger.info(
            "cpq_intent_gateway: llm call failed run_id=%s err=%r",
            get_run_id() or "-", exc,
        )
        return None, 0, 0
    raw = _parse_json_object(text)
    if raw is None:
        return None, pt, ct
    return parse_gateway_intent(raw), pt, ct


def _deterministic_mutating_signals(
    engine: Any,
    question: str,
    attrs: list[ConfigAttr],
    session: CpqSession,
) -> dict[str, set[str]]:
    """Map mutating category → set of variable_names detectors found.

    Only probes detectors with signatures safe to call without full
    rule/BML context. ATTR_CLEAR / ATTR_ACTIVATION need rec_rules /
    hiding_rules — those are left empty here so disagreement forces
    clarify rather than a half-blind agreement.
    """
    out: dict[str, set[str]] = {c.value: set() for c in MUTATING_CATEGORIES}

    def _safe(label: str, fn: Any) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            logger.debug(
                "cpq_intent_gateway: deterministic probe %s failed",
                label, exc_info=True,
            )

    def _probe_change() -> None:
        cr = engine.detect_change_request(
            question, attrs, session.filled, session.filled_multi,
        )
        if cr:
            out[IntentCategory.CHANGE_REQUEST.value].add(cr[0].variable_name)
        multi = engine.detect_change_requests_multi(
            question, attrs, session.filled, session.filled_multi,
        )
        for attr, _hint in multi or []:
            out[IntentCategory.CHANGE_REQUESTS_MULTI.value].add(attr.variable_name)
            out[IntentCategory.CHANGE_REQUEST.value].add(attr.variable_name)
        no_val = engine.detect_change_target_without_value(
            question, attrs, session.filled,
        )
        if no_val:
            out[IntentCategory.CHANGE_TARGET_WITHOUT_VALUE.value].add(
                no_val.variable_name,
            )

    def _probe_removal() -> None:
        removal = engine.detect_multi_select_removal(
            question, attrs, session.filled_multi,
        )
        if removal:
            out[IntentCategory.MULTI_SELECT_REMOVAL.value].add(
                removal[0].variable_name,
            )

    def _probe_bulk() -> None:
        bulk = engine.detect_bulk_quantity_change(
            question, attrs, session.filled_multi,
        )
        if bulk:
            # bulk[0] is the selector variable_name string
            out[IntentCategory.BULK_QUANTITY_CHANGE.value].add(bulk[0])

    _safe("change", _probe_change)
    _safe("removal", _probe_removal)
    _safe("bulk", _probe_bulk)
    return out


def _mutating_agrees(
    result: GatewayIntentResult,
    det_signals: dict[str, set[str]],
    last_qa_variable: str = "",
) -> bool:
    """True when deterministic detectors agree on category + variable_name.

    Also accepts corroboration from conversational recency: a bare-value
    reply ("make it ATT/FirstNet") names no attribute at all, so
    deterministic text-matching detectors can find nothing (or the wrong
    sibling attribute that happens to share the same option value) even
    when the LLM confidently and correctly names the attribute the
    customer was just asking about. docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_
    CLARIFY_ISSUE.md §8 — live-confirmed: "Wireless Carrier" and "Carrier
    Selection" both genuinely accept the same value, so det_signals alone
    can never disambiguate; last_qa_variable is the only signal that can.
    """
    if result.intent_category not in MUTATING_CATEGORIES:
        return True
    cat = result.intent_category.value
    det_vns = det_signals.get(cat, set())
    # CHANGE_REQUEST family: also accept multi-change detector hits
    if result.intent_category == IntentCategory.CHANGE_REQUEST:
        det_vns = det_vns | det_signals.get(
            IntentCategory.CHANGE_REQUESTS_MULTI.value, set(),
        )
    if not result.variable_name:
        return False
    if last_qa_variable and result.variable_name == last_qa_variable:
        return True
    if not det_vns:
        # No deterministic hit at all — treat as disagreement so we clarify
        # rather than mutate solely on LLM word.
        return False
    return result.variable_name in det_vns


def resolve_value_from_ref(
    result: GatewayIntentResult,
    bundles: list[AttrCandidateBundle],
) -> tuple[str | None, str | None]:
    """Map value_ref → (display_name, item_value) via OUR candidate lists.

    The model never supplies item_value text; we look it up by index.
    """
    if result.variable_name is None or result.value_ref is None:
        return None, None
    for b in bundles:
        if b.attr.variable_name != result.variable_name:
            continue
        if 0 <= result.value_ref < len(b.values):
            v = b.values[result.value_ref]
            return v.display_name, v.item_value
        return None, None
    return None, None


def classify_intent(
    question: str,
    attrs: list[ConfigAttr],
    session: CpqSession,
    engine: Any,
    workspace_id: int = 1,
) -> GatewayDecision:
    """LLM-first classification with quarantine, agreement, cache, fallback.

    Returns a GatewayDecision the ask_api orchestrator consumes:
      dispatch — safe to act (handlers resolve values; never writes filled)
      clarify  — ask the user a clarifying_question
      fallback — leave the turn to the existing deterministic path
    """
    settings = get_settings()
    model_id = settings.cpq_intent_gemini_model
    run_id = get_run_id() or "-"

    if not question.strip() or not attrs:
        return GatewayDecision(
            action="fallback", result=None, reason="empty_question_or_attrs",
            model_id=model_id,
        )

    key = _cache_key(question, session, model_id)
    if key in _CACHE:
        cached, pt, ct, mid = _CACHE[key]
        logger.info(
            "cpq_intent_gateway: cache_hit run_id=%s category=%s",
            run_id, cached.intent_category.value,
        )
        display, item = resolve_value_from_ref(
            cached, build_candidate_bundles(attrs, session, question),
        )
        action: Literal["dispatch", "clarify", "fallback"] = (
            "clarify" if cached.intent_category == IntentCategory.AMBIGUOUS
            else "dispatch"
        )
        return GatewayDecision(
            action=action, result=cached, value_display=display,
            value_item=item, prompt_tokens=pt, completion_tokens=ct,
            model_id=mid, cache_hit=True,
        )

    bundles = build_candidate_bundles(attrs, session, question)
    candidate_vns = {b.attr.variable_name for b in bundles}
    value_counts = {b.attr.variable_name: len(b.values) for b in bundles}

    parsed, pt, ct = _llm_classify_once(
        question, bundles, session, model_id, workspace_id,
    )
    total_pt, total_ct = pt, ct

    # Schema retry once
    if parsed is None:
        parsed, pt2, ct2 = _llm_classify_once(
            question, bundles, session, model_id, workspace_id,
            repair_hint="Previous JSON was unparseable or failed schema. "
                        "Return valid JSON only, matching the schema exactly.",
        )
        total_pt += pt2
        total_ct += ct2

    if parsed is None:
        logger.info(
            "cpq_intent_gateway: schema_fail_after_retry run_id=%s → fallback",
            run_id,
        )
        return GatewayDecision(
            action="fallback", result=None, reason="schema_fail",
            prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
        )

    quarantined = validate_gateway_quarantine(
        parsed, question, candidate_vns, value_counts,
    )

    signals = _deterministic_mutating_signals(engine, question, attrs, session)
    det_label = deterministic_category_summary(signals)

    if quarantined.intent_category == IntentCategory.AMBIGUOUS:
        if "variable_name" in (quarantined.rationale or "") or "value_ref" in (
            quarantined.rationale or ""
        ):
            log_rejection(
                run_id, model_id,
                [quarantined.rationale or "quarantine"],
                context="quarantine",
            )
        log_divergence(DivergenceRecord(
            run_id=run_id,
            llm_intent=parsed.intent_category.value if parsed else None,
            deterministic_intent=det_label,
            agreement=False,
            model_id=model_id,
            variable_name=parsed.variable_name if parsed else None,
            rejected=[quarantined.rationale] if quarantined.rationale else [],
            reason="ambiguous_or_quarantine",
        ))
        _store_cache(key, quarantined, total_pt, total_ct, model_id)
        logger.info(
            "cpq_intent_gateway: ambiguous run_id=%s reason=%r",
            run_id, quarantined.rationale,
        )
        return GatewayDecision(
            action="clarify", result=quarantined,
            prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
            reason=quarantined.rationale,
        )

    # Mutating intents: require deterministic agreement
    if quarantined.intent_category in MUTATING_CATEGORIES:
        if not _mutating_agrees(quarantined, signals, session.last_qa_variable):
            clarify = GatewayIntentResult(
                intent_category=IntentCategory.AMBIGUOUS,
                confidence=Confidence.LOW,
                evidence_span=quarantined.evidence_span,
                clarifying_question=(
                    quarantined.clarifying_question
                    or "Just to confirm — which field should I change, and to what?"
                ),
                rationale=(
                    f"mutating_disagreement llm={quarantined.intent_category.value}:"
                    f"{quarantined.variable_name}; det={signals.get(quarantined.intent_category.value)}"
                ),
            )
            warn = log_divergence(DivergenceRecord(
                run_id=run_id,
                llm_intent=quarantined.intent_category.value,
                deterministic_intent=det_label,
                agreement=False,
                model_id=model_id,
                variable_name=quarantined.variable_name,
                rejected=[clarify.rationale],
                reason="mutating_disagreement",
            ))
            if warn:
                clarify.clarifying_question = (
                    f"{clarify.clarifying_question}\n\n{warn}"
                )
            logger.info(
                "cpq_intent_gateway: mutating_disagreement run_id=%s llm=%s vn=%r → clarify",
                run_id, quarantined.intent_category.value, quarantined.variable_name,
            )
            return GatewayDecision(
                action="clarify", result=clarify,
                prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
                reason="mutating_disagreement",
            )

    display, item = resolve_value_from_ref(quarantined, bundles)
    log_divergence(DivergenceRecord(
        run_id=run_id,
        llm_intent=quarantined.intent_category.value,
        deterministic_intent=det_label or quarantined.intent_category.value,
        agreement=True,
        model_id=model_id,
        variable_name=quarantined.variable_name,
        reason="dispatch",
    ))
    _store_cache(key, quarantined, total_pt, total_ct, model_id)
    logger.info(
        "cpq_intent_gateway: dispatch run_id=%s category=%s vn=%r value_ref=%r "
        "evidence=%r tokens=(%d,%d) model=%s",
        run_id, quarantined.intent_category.value, quarantined.variable_name,
        quarantined.value_ref, quarantined.evidence_span, total_pt, total_ct, model_id,
    )
    return GatewayDecision(
        action="dispatch", result=quarantined,
        value_display=display, value_item=item,
        prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
    )


def _store_cache(
    key: str, result: GatewayIntentResult, pt: int, ct: int, model_id: str,
) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop an arbitrary oldest-ish entry (insertion order on 3.7+)
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[key] = (result, pt, ct, model_id)


def clear_gateway_cache() -> None:
    """Test helper — wipe the process-local intent cache."""
    _CACHE.clear()


# ── Top-level /ask route classifier (Prompt 3) ───────────────────────────────
# Decides QUOTE vs QA vs AMBIGUOUS vs OFF_TOPIC for cold-start turns.
# Live CPQ sessions never call this — they go straight to _run_cpq_turn.

AskRoute = Literal["quote", "qa", "ambiguous", "off_topic"]

_ROUTE_SCHEMA: dict = {
    "type": "object",
    "required": ["route", "confidence", "clarifying_question", "rationale"],
    "properties": {
        "route": {
            "type": "string",
            "enum": ["quote", "qa", "ambiguous", "off_topic"],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "clarifying_question": {
            "type": ["string", "null"],
            "description": "Required when route=ambiguous; otherwise null.",
        },
        "rationale": {"type": "string"},
    },
}

# Few-shot positives (owner-provided) + anti-patterns for negatives.
_ROUTE_FEW_SHOTS = """
POSITIVE examples (route correctly):

1) Q: "I want to order APX Next radios 50 qty for customer City of Houston whose destination country is United States"
   → route=quote
   WHY: full order intent with product + qty + destination. Country is ALREADY stated — do not treat as incomplete country-only prompt.

2) Q: "change the hardware version"
   → route=quote
   WHY: mid-configuration change request. Hand to the CPQ guided engine (even if no session yet, it will open/continue config). Never invent option lists outside the engine.

3) Q: "astra in astrological sense"
   → route=off_topic
   WHY: explicitly non-product/non-quoting. Do NOT force into CPQ or invent catalog facts.

NEGATIVE examples (wrong behaviors — NEVER do these):

N1) Q: "i want to order APX Next radios for destination country United States"
   WRONG: ask again "what's the destination country?" when the user already said United States.
   RIGHT: route=quote (country is present; engine extracts it).

N2) Q: "what are the options for product"
   WRONG: silently switch product family / continue under softwareSolutions_BOM.
   RIGHT: route=qa — catalog options question, not a product-family switch.

N3) Q: (session already on aSTRO25_bom) "yes so under softwareSolutions_BOM I am looking for CommandCentral Aware"
   WRONG: pretend we are already on softwareSolutions_BOM without an explicit switch.
   RIGHT: route=quote so the CPQ engine can run its product-switch confirmation (yes/no discard) — never silent family hop.
"""


@dataclass
class AskRouteDecision:
    """Top-level /ask routing decision from the intent gateway."""

    route: AskRoute
    confidence: str
    clarifying_question: str | None
    rationale: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_id: str = ""
    timed_out: bool = False
    error: str = ""
    # Deterministic auditor (is_cpq_question) for agreement logs.
    det_is_cpq: bool | None = None
    agreement: bool | None = None


def _parse_route(raw: dict | None) -> AskRouteDecision | None:
    if not isinstance(raw, dict):
        return None
    route = raw.get("route")
    if route not in ("quote", "qa", "ambiguous", "off_topic"):
        return None
    conf = raw.get("confidence") or "low"
    if conf not in ("high", "medium", "low"):
        conf = "low"
    cq = raw.get("clarifying_question")
    if cq is not None and not isinstance(cq, str):
        cq = None
    if route == "ambiguous" and not cq:
        cq = (
            "I want to make sure I help correctly — are you trying to "
            "configure/quote a product, or ask a general question about one?"
        )
    if conf == "low" and route in ("quote", "qa"):
        # Low confidence → force clarify rather than wrong path
        return AskRouteDecision(
            route="ambiguous",
            confidence="low",
            clarifying_question=cq or (
                "Are you looking to place/configure a quote, or ask a "
                "product question?"
            ),
            rationale=f"low_confidence_downgrade; {raw.get('rationale') or ''}",
        )
    return AskRouteDecision(
        route=route,  # type: ignore[arg-type]
        confidence=conf,
        clarifying_question=cq,
        rationale=str(raw.get("rationale") or ""),
    )


def classify_ask_route(
    question: str,
    *,
    workspace_id: int = 1,
    session_hint: str = "",
    det_is_cpq: bool | None = None,
    timeout_s: float | None = None,
) -> AskRouteDecision:
    """One structured call: quote | qa | ambiguous | off_topic.

    Incorporates owner few-shot positives/negatives. On timeout/error
    returns route fallback signal via ``error`` / ``timed_out`` so the
    caller can escape to the deterministic gate.
    """
    settings = get_settings()
    model_id = settings.cpq_intent_gemini_model
    timeout = timeout_s if timeout_s is not None else float(
        getattr(settings, "cpq_intent_timeout_s", 10.0) or 10.0,
    )
    run_id = get_run_id() or "-"

    # N10: hard off-topic veto before any LLM call (saves latency; no misroute).
    if hard_off_topic(question):
        logger.info(
            "cpq_ask_route: HARD_OFF_TOPIC run_id=%s q=%r", run_id, question[:80],
        )
        return AskRouteDecision(
            route="off_topic",
            confidence="high",
            clarifying_question=None,
            rationale="hard_off_topic_veto",
            model_id=model_id,
            det_is_cpq=det_is_cpq,
            agreement=(det_is_cpq is False) if det_is_cpq is not None else None,
        )

    sys = (
        "You are the top-level router for an enterprise product-configuration "
        "and quoting assistant (Aryx CPQ).\n"
        "Classify ONE user message into exactly one route:\n"
        "- quote: order/configure/change a product quote or config value\n"
        "- qa: ask about options, meanings, or catalog facts without "
        "changing configuration state\n"
        "- ambiguous: could be quote OR qa (or unclear) — must ask a "
        "clarifying_question\n"
        "- off_topic: not product configuration or quoting at all\n\n"
        f"Reply ONLY as JSON matching:\n{json.dumps(_ROUTE_SCHEMA, indent=1)}\n\n"
        f"{_ROUTE_FEW_SHOTS}\n"
        "Rules:\n"
        "1. If destination country (or product + qty + country) is already "
        "in the message, still route=quote — never invent a missing-country "
        "gate at the router layer.\n"
        "2. 'what are the options for X' / 'what values…' → qa, never a "
        "silent product-family switch.\n"
        "3. Astrology, weather, sports, jokes → off_topic.\n"
        "4. Mid-session product-family names that differ from the active "
        "session → quote (engine owns switch confirmation).\n"
    )
    session_block = (
        f"SESSION HINT: {session_hint}\n" if session_hint else "SESSION HINT: none (cold start)\n"
    )
    user = f"{session_block}USER MESSAGE:\n{question}\n"

    def _call() -> tuple[str, int, int]:
        return _pinned_chat(sys, user, model_id, workspace_id)

    text, pt, ct = "", 0, 0
    try:
        # Hard timeout — escape hatch for the orchestrator.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_call)
            text, pt, ct = fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "cpq_ask_route: TIMEOUT run_id=%s model=%s timeout_s=%s",
            run_id, model_id, timeout,
        )
        return AskRouteDecision(
            route="quote",  # unused when error set
            confidence="low",
            clarifying_question=None,
            rationale="timeout",
            model_id=model_id,
            timed_out=True,
            error="timeout",
            det_is_cpq=det_is_cpq,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cpq_ask_route: ERROR run_id=%s model=%s err=%r",
            run_id, model_id, exc,
        )
        return AskRouteDecision(
            route="quote",
            confidence="low",
            clarifying_question=None,
            rationale=f"error:{exc!r}",
            model_id=model_id,
            error=str(exc),
            det_is_cpq=det_is_cpq,
        )

    raw = _parse_json_object(text)
    parsed = _parse_route(raw)
    if parsed is None:
        # One schema retry
        try:
            text2, pt2, ct2 = _pinned_chat(
                sys + "\nPREVIOUS OUTPUT INVALID. Return valid JSON only.\n",
                user, model_id, workspace_id,
            )
            pt += pt2
            ct += ct2
            parsed = _parse_route(_parse_json_object(text2))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cpq_ask_route: retry failed run_id=%s err=%r", run_id, exc)
            parsed = None

    if parsed is None:
        return AskRouteDecision(
            route="quote",
            confidence="low",
            clarifying_question=None,
            rationale="double_validation_failure",
            prompt_tokens=pt,
            completion_tokens=ct,
            model_id=model_id,
            error="double_validation_failure",
            det_is_cpq=det_is_cpq,
        )

    # N10 post-LLM: if hard off-topic lexicon matches, never keep quote/qa.
    if hard_off_topic(question) and parsed.route in ("quote", "qa", "ambiguous"):
        parsed = AskRouteDecision(
            route="off_topic",
            confidence="high",
            clarifying_question=None,
            rationale=f"hard_off_topic_override; was={parsed.route}",
            prompt_tokens=pt,
            completion_tokens=ct,
            model_id=model_id,
        )

    parsed.prompt_tokens = pt
    parsed.completion_tokens = ct
    parsed.model_id = model_id
    parsed.det_is_cpq = det_is_cpq
    if det_is_cpq is not None:
        # Agreement: quote ↔ det True; off_topic/qa ↔ det False is soft.
        llm_cpq = parsed.route in ("quote", "ambiguous")
        parsed.agreement = (llm_cpq == det_is_cpq) or parsed.route == "ambiguous"
        log_divergence(DivergenceRecord(
            run_id=run_id,
            llm_intent=parsed.route,
            deterministic_intent="cpq" if det_is_cpq else "not_cpq",
            agreement=bool(parsed.agreement),
            model_id=model_id,
            reason="ask_route",
        ))
    logger.info(
        "cpq_ask_route: run_id=%s route=%s conf=%s det_is_cpq=%s agree=%s "
        "model=%s tokens=(%d,%d) rationale=%r",
        run_id, parsed.route, parsed.confidence, det_is_cpq, parsed.agreement,
        model_id, pt, ct, parsed.rationale,
    )
    return parsed


def map_route_to_det_expectation(route: AskRoute) -> bool:
    """Whether the deterministic is_cpq_question auditor should be True."""
    return route in ("quote", "ambiguous")
