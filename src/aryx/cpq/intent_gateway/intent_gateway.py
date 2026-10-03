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

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), candidate
building (`cpq.intent_gateway_candidates`), deterministic-agreement checks
(`cpq.intent_gateway_agreement`), and the classification cache (`cpq.
intent_gateway_cache`) live in their own modules and are re-imported here.
`_pinned_chat`, `_llm_classify_once`, `classify_intent`, and
`classify_ask_route` all stay together in this hub: every one of them
either calls `_pinned_chat` directly or is `_pinned_chat` itself, and
`test_cpq_intent_gateway.py`/`test_cpq_ask_route_fewshots.py` patch
`aryx.cpq.intent_gateway.intent_gateway._pinned_chat`/`.get_settings` directly — moving
any of these apart would require every caller to access `_pinned_chat` via
a full module-attribute reference (`intent_gateway._pinned_chat(...)`
instead of a bound `from...import`) to keep the patch intercepting it,
a departure from this codebase's normal import style not worth making for
a coupling this central.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.intent_gateway import intent_gateway_attr_route as _attr_route
from aryx.cpq.intent_gateway.intent_gateway_agreement import (
    MUTATING_CATEGORIES,
    _deterministic_mutating_signals,
    _mutating_agrees,
)
from aryx.cpq.intent_gateway.intent_gateway_cache import (
    _cache_key,
    _CACHE,
    _store_cache,
    clear_gateway_cache,
    session_state_hash,
)
from aryx.cpq.intent_gateway.intent_gateway_candidates import (
    AttrCandidateBundle,
    ValueCandidate,
    _ATTR_CAP,
    _VALUE_CAP,
    _format_candidates_for_prompt,
    _rank_value_candidates_by_relevance,
    build_candidate_bundles,
    resolve_value_from_ref,
)
from aryx.cpq.intent_schema.intent_schema import (
    GATEWAY_INTENT_JSON_SCHEMA,
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    parse_gateway_intent,
    validate_gateway_quarantine,
)
from aryx.cpq.logging_context import get_run_id
from aryx.cpq.state import ConfigAttr, CpqSession
from aryx.cpq.telemetry import (
    DivergenceRecord,
    deterministic_category_summary,
    log_divergence,
    log_rejection,
)
from aryx.llm import complete_text
from aryx.raven_log import raven_log, submit_ctx

logger = logging.getLogger(__name__)

__all__ = [
    "GATEWAY_INTENT_JSON_SCHEMA",
    "MUTATING_CATEGORIES",
    "AskRoute",
    "AskRouteDecision",
    "AttrCandidateBundle",
    "GatewayDecision",
    "ValueCandidate",
    "build_candidate_bundles",
    "clear_gateway_cache",
    "classify_ask_route",
    "classify_intent",
    "hard_off_topic",
    "map_route_to_det_expectation",
    "mark_top_level_route_used",
    "resolve_value_from_ref",
    "session_state_hash",
    "soft_quote_heuristic",
    "top_level_route_used",
]

# N4: when top-level classify_ask_route already ran this turn, skip the
# mid-session STEP-6 gateway so the turn pays one LLM classification call.
_top_level_route_used: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cpq_top_level_route_used", default=False,
)

# N10: hard off-topic veto — do not trust LLM if these fire.
_OFF_TOPIC_HARD = re.compile(
    r"\b(astrolog(?:y|ical)?|horoscope|zodiac|tarot|"
    r"weather(?:\s*forecast)?|world\s*cup|tell\s+me\s+a\s+joke|knock[\s-]knock)\b",
    re.IGNORECASE,
)
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8: a PROVISIONAL strong/weak
# split of _OFF_TOPIC_HARD's own terms, used ONLY by the shadow-logging
# below (cpq_off_topic_veto_shadow_enabled) -- never consulted by
# hard_off_topic() itself, so it can never change real routing. Seeded
# from the audit's own explicit example ("real quotes mentioning weather
# can still be silently rejected as off-topic") -- "weather" and "world
# cup" are the two terms with a plausible real-product-question false-
# positive (a customer asking how a radio holds up "in bad weather", or
# a shipment tied to a "world cup" event); the rest (astrology/horoscope/
# zodiac/tarot/jokes) have no such collision in a CPQ context.
_OFF_TOPIC_WEAK_TERMS = frozenset({"weather", "world cup"})


def _off_topic_shadow_term_strength(question: str) -> str | None:
    """Which _OFF_TOPIC_HARD term matched, and whether it's in the
    PROVISIONAL weak set above -- "weak", "strong", or None (no match).
    Shadow-measurement only; see cpq_off_topic_veto_shadow_enabled."""
    m = _OFF_TOPIC_HARD.search(question or "")
    if not m:
        return None
    matched = re.sub(r"\s+", " ", m.group(1).lower()).strip()
    for weak in _OFF_TOPIC_WEAK_TERMS:
        if weak in matched or matched in weak:
            return "weak"
    return "strong"


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


# Feature/region product-SEARCH intent (2026-09-16 andie analysis) --
# distinct from CPQ configuration ("set region to NA") and from generic QA.
# Deliberately deterministic/regex-only, not routed through the gateway LLM
# (classify_ask_route): this only needs to catch a narrow, high-precision
# pattern -- "which/what/list/show/find products/models ... region X /
# feature Y" -- and a false negative just falls through to the existing
# CPQ/QA router unchanged, so there is no correctness cost to keeping this
# conservative. A false POSITIVE would be worse (hijacking a real CPQ turn
# into a search response), which is why _SEARCH_TRIGGER requires both a
# search verb AND a product/model/catalog noun, not either alone.
_SEARCH_TRIGGER = re.compile(
    r"\b(which|what|list|show|find)\b.{0,40}\b(product|model|catalog)s?\b",
    re.IGNORECASE,
)
_REGION_SEARCH = re.compile(
    r"\bregion\s+([A-Za-z]{2,15})\b|\bin\s+([A-Za-z]{2,15})\s+region\b",
    re.IGNORECASE,
)
# "Feature Type" is the only human label CONFIRMED real against
# attrToVarMapping.csv this session (2026-09-15 hardcoding audit) -- other
# labels exist in principle (resolve_variable_name_for_role is generic),
# but this deterministic extractor only ever emits that one confirmed
# label, never a guessed one.
_FEATURE_SEARCH = re.compile(
    r"\bfeature(?:\s+type)?\s*[:\s]\s*([A-Za-z0-9][A-Za-z0-9 \-]{1,40}?)(?=[?.]|$)|"
    r"\b(?:support|supports|with|has|have)\s+([A-Za-z0-9][A-Za-z0-9 \-]{1,40}?)\s+feature\b",
    re.IGNORECASE,
)


def detect_feature_region_search(
    question: str,
) -> tuple[str | None, str | None, str | None]:
    """Deterministic (region, feature_label, feature_value) extraction for
    a feature/region product-search question, or (None, None, None) if the
    question doesn't match this narrow pattern -- see search_products_
    combined() (aryx.graph.feature_search) for what consumes this.

    Returns feature_label="Feature Type" whenever a feature value is
    extracted -- the only human label confirmed real this session; never
    a broader guess at other possible roles.
    """
    q = question or ""
    if not _SEARCH_TRIGGER.search(q):
        return None, None, None

    region = None
    region_match = _REGION_SEARCH.search(q)
    if region_match:
        region = (region_match.group(1) or region_match.group(2) or "").strip() or None

    feature_value = None
    feature_match = _FEATURE_SEARCH.search(q)
    if feature_match:
        feature_value = (
            feature_match.group(1) or feature_match.group(2) or ""
        ).strip() or None
    feature_label = "Feature Type" if feature_value else None

    if region is None and feature_value is None:
        return None, None, None
    return region, feature_label, feature_value


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
    # Log BEFORE the network call, not just after — confirmed live
    # (2026-08-14 incident) a request can sit here for the full
    # ARYX_LLM_TIMEOUT window (900s default, docker-compose.yml) with
    # nothing in the logs to show an LLM call was even in flight, only the
    # eventual latency_ms line below IF/when it returns at all.
    logger.info(
        "cpq_intent_gateway_start: model=%s provider=%s run_id=%s",
        model_id, provider, get_run_id() or "-",
    )
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
        "6. \"approval\" vs \"decline\" (ISSUE-002 — do not confuse these): "
        "\"approval\" is ONLY for the customer confirming/accepting the "
        "configuration as-is so it can be submitted -- \"yes\", \"confirm\", "
        "\"looks good, submit\", \"go ahead\", \"that's correct\". "
        "\"decline\" is for the customer explicitly rejecting/refusing to "
        "submit -- \"no, decline that\", \"don't submit yet\", \"cancel\", "
        "\"reject\", \"not ready\", \"hold on\". A bare negative word or a "
        "message that says no/don't/not is NEVER \"approval\" -- when in "
        "doubt between the two, prefer \"decline\" (an unwanted decline is "
        "recoverable by asking again; an unwanted approval submits a real "
        "order the customer did not agree to).\n"
        "7. A pending attribute (see SESSION PENDING below, if present) is relevant to "
        "classifying THIS message only if the message's own content actually relates to "
        "that attribute's real concept (its label, or its value candidates) -- never infer "
        "relevance just because something is pending and the message happens to mention a "
        "related-sounding word. A pending attribute must never be treated as \"what the "
        "customer means\" for ANY category (a quantity change, a country change, approval, "
        "or anything else) unless the pending attribute's own label genuinely matches that "
        "category's concept. When the message's real subject doesn't match the pending "
        "attribute at all, classify based on the message's actual content, not the fact "
        "that something else happens to be pending.\n"
        "8. PRODUCT_QUANTITY_CHANGE vs ambiguous: a bare/generic quantity reference "
        "(\"that quantity\", \"the quantity\") with a clearly stated new number, and no "
        "specific catalog item named in the message, should be classified as "
        "PRODUCT_QUANTITY_CHANGE with high confidence -- do not default to ambiguous just "
        "because no candidate attribute in CANDIDATE ATTRIBUTES matches; PRODUCT_QUANTITY_"
        "CHANGE deliberately has no attribute target (variable_name=null is correct for it).\n"
    )
    if repair_hint:
        sys += f"\nPREVIOUS ATTEMPT FAILED VALIDATION: {repair_hint}\nFix the JSON.\n"

    pending_bits: list[str] = []
    if session.pending_variables:
        _pending_vn = session.pending_variables[0]
        # docs/CPQ_GATEWAY_PENDING_ATTR_QUANTITY_CONFLATION_PLAN_2026_08_17.md --
        # a bare variable_name gives the model no way to judge whether this
        # pending attribute has anything to do with the current message's
        # subject, inviting it to hallucinate relevance from co-occurrence
        # alone (confirmed live: a pending Hardware Version question plus a
        # quantity-change message was misclassified as being about "the
        # recently discussed line item"). The real label lets the model
        # judge genuine relevance instead of guessing from the bare name.
        _pending_bundle = next(
            (b for b in bundles if b.attr.variable_name == _pending_vn), None,
        )
        pending_bits.append(
            f"pending_attr={_pending_vn} (label: {_pending_bundle.attr.display_label!r})"
            if _pending_bundle is not None
            else f"pending_attr={_pending_vn}"
        )
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
    if session.last_qa_variables:
        _multi_qa = len(session.last_qa_variables) > 1
        pending_bits.append(
            "customer_last_asked_about="
            + "|".join(session.last_qa_variables)
            + (
                " (their immediately preceding message asked about ALL of "
                "these attributes at once — a short follow-up naming a "
                "value for each most likely refers to them respectively, "
                "even if a value is also technically valid for another "
                "attribute)"
                if _multi_qa else
                " (their immediately preceding message was a question about "
                "this attribute — a short follow-up like 'make it X' most "
                "likely refers to it, even if X is also technically a valid "
                "value for another attribute)"
            )
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


def classify_intent(
    question: str,
    attrs: list[ConfigAttr],
    session: CpqSession,
    engine: Any,
    workspace_id: int = 1,
    hiding_rules: list | None = None,
    rec_rules: list | None = None,
    con_rules: list | None = None,
    bml_eval: Any = None,
    catalog_prefix: str = "",
) -> GatewayDecision:
    """LLM-first classification with quarantine, agreement, cache, fallback.

    `hiding_rules`/`rec_rules`/`con_rules`/`bml_eval`/`catalog_prefix`
    (docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2b
    follow-up, all optional/default None): threaded through to
    `_deterministic_mutating_signals` so ATTR_ACTIVATION/ATTR_CLEAR can
    be genuinely probed instead of permanently forced to "disagree".
    Any existing caller that doesn't pass them keeps working exactly as
    before — those two categories simply stay unprobed.

    Returns a GatewayDecision the ask_api orchestrator consumes:
      dispatch — safe to act (handlers resolve values; never writes filled)
      clarify  — ask the user a clarifying_question
      fallback — leave the turn to the existing deterministic path
    """
    settings = get_settings()
    model_id = settings.cpq_intent_gemini_model
    run_id = get_run_id() or "-"

    if not question.strip():
        raven_log("DEBUG", "P4", "ask.intent.gateway empty question, fallback", context={
            "selected_option": "fallback", "reason_code": "EMPTY_QUESTION",
            "available_options": ["dispatch", "clarify", "fallback"], "model_id": model_id})
        return GatewayDecision(
            action="fallback", result=None, reason="empty_question",
            model_id=model_id,
        )
    # `attrs` may legitimately be empty — callers confirming a
    # session-level, no-target category (PRODUCT_QUANTITY_CHANGE,
    # COUNTRY_CHANGE) call this before the catalog is even loaded this
    # turn (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md
    # Issue 6/7 follow-up). Previously bailing to "fallback" here meant
    # the LLM was NEVER actually consulted for those two categories —
    # `_llm_confirm_deterministic_intent` always saw `result=None` and
    # always rejected, silently making the country-change gate a no-op
    # in production despite passing every test (tests mock this
    # function directly, bypassing this check). `build_candidate_
    # bundles`/`_format_candidates_for_prompt` both tolerate an empty
    # `attrs` list already (empty candidate block, not a crash) — a
    # target-requiring category simply can't resolve a `variable_name`
    # against an empty candidate set and correctly quarantines to
    # ambiguous/fallback downstream, so this is safe for every category,
    # not just the two that motivated it.

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

    timeout = float(getattr(settings, "cpq_intent_classify_timeout_s", 120.0) or 120.0)

    def _classify_with_timeout(
        repair_hint: str = "",
    ) -> tuple[GatewayIntentResult | None, int, int, bool]:
        """Returns (parsed, pt, ct, timed_out) -- never raises TimeoutError.

        Deliberately does NOT use the executor as a context manager: `with
        ThreadPoolExecutor() as pool:` calls `pool.__exit__` ->
        `shutdown(wait=True)` as soon as the block is left for ANY reason,
        including via an exception -- so `fut.result(timeout=timeout)`
        raising TimeoutError still blocks this call until the orphaned
        task actually finishes, defeating the timeout entirely. Confirmed
        live: a lambda sleeping 3s with `timeout=0.5` doesn't return until
        ~3s even though TimeoutError fires at 0.5s. `shutdown(wait=False)`
        after handling the result/timeout lets the orphaned thread finish
        and get GC'd in the background instead, so this function actually
        returns within `timeout` seconds as advertised.
        """
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = submit_ctx(
            pool, _llm_classify_once, question, bundles, session, model_id,
            workspace_id, repair_hint,
        )
        try:
            parsed, pt, ct = fut.result(timeout=timeout)
            return parsed, pt, ct, False
        except concurrent.futures.TimeoutError:
            logger.warning(
                "cpq_intent_gateway: TIMEOUT run_id=%s model=%s timeout_s=%s",
                run_id, model_id, timeout,
            )
            return None, 0, 0, True
        finally:
            pool.shutdown(wait=False)

    parsed, pt, ct, timed_out = _classify_with_timeout()
    total_pt, total_ct = pt, ct

    if timed_out:
        return GatewayDecision(
            action="fallback", result=None, reason="timeout",
            prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
        )

    # Schema retry once
    if parsed is None:
        parsed, pt2, ct2, timed_out = _classify_with_timeout(
            repair_hint="Previous JSON was unparseable or failed schema. "
                        "Return valid JSON only, matching the schema exactly.",
        )
        total_pt += pt2
        total_ct += ct2
        if timed_out:
            return GatewayDecision(
                action="fallback", result=None, reason="timeout",
                prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
            )

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

    signals = _deterministic_mutating_signals(
        engine, question, attrs, session,
        hiding_rules=hiding_rules, rec_rules=rec_rules, con_rules=con_rules,
        bml_eval=bml_eval, workspace_id=workspace_id, catalog_prefix=catalog_prefix,
    )
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

    # PR #205 review fix (High finding #2): APPROVAL is NOT in
    # MUTATING_CATEGORIES and never requires `detect_approval()` to
    # positively agree — the LLM was already correctly classifying
    # genuine approvals before ISSUE-002's fix; gating on regex agreement
    # would reject any approval phrasing the LLM correctly recognizes but
    # the hand-written regex doesn't happen to cover, trading one bug for
    # another. Instead, a DECLINE-only veto: if the deterministic decline
    # detector ALSO fires on this exact text, that's a genuine conflict
    # signal (the customer's own words read as a rejection even though
    # the LLM called it an approval) worth clarifying over, in the one
    # direction where a wrong guess is costly (approving a decline).
    if (
        quarantined.intent_category == IntentCategory.APPROVAL
        and engine is not None
        and engine.detect_decline(question)
    ):
        clarify = GatewayIntentResult(
            intent_category=IntentCategory.AMBIGUOUS,
            confidence=Confidence.LOW,
            evidence_span=quarantined.evidence_span,
            clarifying_question=(
                "Just to confirm — would you like me to submit this "
                "configuration, or were you declining it?"
            ),
            rationale=(
                "approval_decline_conflict: LLM classified approval but "
                "detect_decline() also matched this text"
            ),
        )
        log_divergence(DivergenceRecord(
            run_id=run_id,
            llm_intent=quarantined.intent_category.value,
            deterministic_intent=det_label,
            agreement=False,
            model_id=model_id,
            variable_name=quarantined.variable_name,
            rejected=[clarify.rationale],
            reason="approval_decline_conflict",
        ))
        logger.info(
            "cpq_intent_gateway: approval_decline_conflict run_id=%s → clarify",
            run_id,
        )
        return GatewayDecision(
            action="clarify", result=clarify,
            prompt_tokens=total_pt, completion_tokens=total_ct, model_id=model_id,
            reason="approval_decline_conflict",
        )

    # Mutating intents: require deterministic agreement
    if quarantined.intent_category in MUTATING_CATEGORIES:
        if not _mutating_agrees(
            quarantined, signals, session.last_qa_variables,
            question=question, engine=engine,
        ):
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


# ── Top-level /ask route classifier (Prompt 3) ───────────────────────────────
# Decides QUOTE vs QA vs AMBIGUOUS vs OFF_TOPIC for cold-start turns.
# Live CPQ sessions never call this — they go straight to _run_cpq_turn.

AskRoute = Literal["quote", "qa", "ambiguous", "off_topic", "attribute_search"]

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
        "quantity": {
            "type": ["integer", "null"],
            "description": (
                "The overall order quantity, if genuinely stated anywhere "
                "in the message. Never guess or invent one."
            ),
        },
        "country": {
            "type": ["string", "null"],
            "description": (
                "The destination country, if genuinely stated anywhere in "
                "the message. Never guess or invent one."
            ),
        },
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

4) Q: "I need pricing for a dozen APX NEXT standard models in the United States"
   → route=quote, quantity=12, country="United States"
   WHY: "a dozen" is a genuine, plainly stated quantity (=12) and the country is stated even though an article ("the") sits between the preposition and the name — extract both exactly as meant, never leave them null just because the phrasing is unusual.

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
    # docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md turn-1 unified
    # extraction plan — quantity/country stated in the cold-start message,
    # extracted by this SAME call rather than a second, separate LLM call.
    # Raw, UNVALIDATED model output — the caller MUST still run quantity
    # through is_valid_product_quantity and country through
    # is_recognized_country before trusting either, exactly like every
    # other free-text LLM extraction in this codebase.
    quantity: int | None = None
    country: str | None = None
    # route=attribute_search only (intent_gateway_attr_route.py): the raw
    # attribute label/value the user typed, UNVALIDATED -- grounding against
    # the catalog is the caller's job, same as quantity/country.
    attribute_label: str | None = None
    attribute_value: str | None = None


_classify_intent_inner = classify_intent  # the original, wrapped below to log its decision


def classify_intent(question: str, *args: Any, **kwargs: Any) -> GatewayDecision:
    """Run the mid-session intent gateway and record the action chosen and why."""
    _t0 = time.monotonic()
    decision = _classify_intent_inner(question, *args, **kwargs)
    res = getattr(decision, "result", None)
    cat = getattr(getattr(res, "intent_category", None), "value", None)
    conf = getattr(getattr(res, "confidence", None), "value", None)
    raven_log("DEBUG", "P4", "ask.intent.gateway classify_intent decided", context={
        "selected_option": decision.action,
        "available_options": ["dispatch", "clarify", "fallback"],
        "reason_code": decision.reason or ("CACHE_HIT" if decision.cache_hit else "CLASSIFIED"),
        "policy_version": "intent_gateway", "category": cat, "confidence": conf,
        "variable_name": getattr(res, "variable_name", None), "cache_hit": decision.cache_hit,
        "model_id": decision.model_id, "prompt_tokens": decision.prompt_tokens,
        "completion_tokens": decision.completion_tokens,
        "duration_ms": int((time.monotonic() - _t0) * 1000),
        "question_len": len(question or ""), "ran_and_did_nothing": decision.action == "fallback",
    })
    return decision


def _parse_route(
    raw: dict | None, *, allow_attribute_search: bool = False,
) -> AskRouteDecision | None:
    if not isinstance(raw, dict):
        return None
    route = raw.get("route")
    extra = (_attr_route.ATTRIBUTE_SEARCH,) if allow_attribute_search else ()
    if route not in ("quote", "qa", "ambiguous", "off_topic", *extra):
        return None
    route, attr_label, attr_value, raw = _attr_route.resolve_attr_route(raw, route)
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
    # docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md turn-1 unified
    # extraction plan — type-checked only here (fail-closed to None on any
    # type mismatch); real semantic validation (is_valid_product_quantity/
    # is_recognized_country) is the CALLER's job, same "parse here, trust
    # nothing, validate at the consumer" split every other _llm_*/gateway
    # parse function in this codebase already follows.
    qty_raw = raw.get("quantity")
    quantity = qty_raw if isinstance(qty_raw, int) and not isinstance(qty_raw, bool) else None
    country_raw = raw.get("country")
    country = country_raw.strip() if isinstance(country_raw, str) and country_raw.strip() else None
    # ISSUE-007 fix #3 (secondary backstop, docs/CPQ_E2E_ISSUES_001_002_
    # 003_004_FIX_PLAN_2026_08_17.md): normalize whatever the model
    # extracted through the SAME generic alias-group resolution every
    # other country-validation call site uses (`CpqEngine.
    # is_recognized_country` -> `_country_alias_group`), so route_meta.
    # country itself carries the clean canonical form forward (e.g. an
    # LLM that copied "US.A" verbatim into its own JSON still resolves
    # to "United States" here) rather than relying only on the
    # downstream `is_recognized_country` re-check to catch it. Falls
    # back to the model's raw string when it isn't alias-recognized (a
    # genuine miss, or free-text noise) — real semantic
    # accept/reject is still the CALLER's job, this only cleans up a
    # value that IS a real country into its canonical spelling.
    if country:
        country = CpqEngine.is_recognized_country(country) or country
    if conf == "low" and route in ("quote", "qa", _attr_route.ATTRIBUTE_SEARCH):
        # Low confidence → force clarify rather than wrong path
        return AskRouteDecision(
            route="ambiguous",
            confidence="low",
            clarifying_question=cq or (
                "Are you looking to place/configure a quote, or ask a "
                "product question?"
            ),
            rationale=f"low_confidence_downgrade; {raw.get('rationale') or ''}",
            quantity=quantity,
            country=country,
        )
    return AskRouteDecision(
        route=route,  # type: ignore[arg-type]
        confidence=conf,
        clarifying_question=cq,
        rationale=str(raw.get("rationale") or ""),
        quantity=quantity,
        country=country,
        attribute_label=attr_label,
        attribute_value=attr_value,
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
        getattr(settings, "cpq_intent_timeout_s", 120.0) or 120.0,
    )
    run_id = get_run_id() or "-"

    # N10: hard off-topic veto before any LLM call (saves latency; no misroute).
    if hard_off_topic(question):
        logger.info(
            "cpq_ask_route: HARD_OFF_TOPIC run_id=%s q=%r", run_id, question[:80],
        )
        if settings.cpq_off_topic_veto_shadow_enabled:
            logger.info(
                "cpq_off_topic_veto_shadow: run_id=%s q=%r term_strength=%s "
                "site=pre_llm (no LLM verdict available -- veto skipped the "
                "call)", run_id, question[:80],
                _off_topic_shadow_term_strength(question),
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

    attr_on = _attr_route.is_enabled(settings)
    schema = _attr_route.extend_schema(_ROUTE_SCHEMA) if attr_on else _ROUTE_SCHEMA
    sys = (
        "You are the top-level router for an enterprise product-configuration "
        "and quoting assistant (Aryx CPQ).\n"
        "Classify ONE user message into exactly one route:\n"
        "- quote: order/configure/change a product quote or config value\n"
        "- qa: ask about options, meanings, or catalog facts without "
        "changing configuration state\n"
        "- ambiguous: could be quote OR qa (or unclear) — must ask a "
        "clarifying_question\n"
        "- off_topic: not product configuration or quoting at all\n"
        f"{_attr_route.ROUTE_LINE if attr_on else ''}\n"
        f"Reply ONLY as JSON matching:\n{json.dumps(schema, indent=1)}\n\n"
        f"{_ROUTE_FEW_SHOTS}\n"
        f"{_attr_route.FEW_SHOTS + chr(10) if attr_on else ''}"
        "Rules:\n"
        "1. If destination country (or product + qty + country) is already "
        "in the message, still route=quote — never invent a missing-country "
        "gate at the router layer.\n"
        "2. 'what are the options for X' / 'what values…' → qa, never a "
        "silent product-family switch.\n"
        "3. Astrology, weather, sports, jokes → off_topic.\n"
        "4. Mid-session product-family names that differ from the active "
        "session → quote (engine owns switch confirmation).\n"
        "5. If a specific order quantity or destination country is stated "
        "anywhere in the message, extract it into the quantity/country "
        "fields exactly as stated (quantity as an integer, country as its "
        "plain name) — including unusual phrasing (word-form numbers like "
        "'a dozen', an article between a preposition and the country "
        "name). Never invent a value that isn't genuinely there — leave "
        "the field null instead.\n"
        "6. Recognize a stated country regardless of punctuation, "
        "spacing, letter case, or which real-world form the customer "
        "used — common name, official name, ISO alpha-2/alpha-3 code, or "
        "a well-known colloquial short form. Always output the plain "
        "common name once recognized, e.g. as a PATTERN to generalize to "
        "any country, not an exhaustive list:\n"
        "   - 'US' / 'U.S.' / 'U.S.A.' / 'USA' / 'US.A' / 'America' -> United States\n"
        "   - 'UK' / 'U.K.' -> United Kingdom\n"
        "   - 'UAE' / 'U.A.E' -> United Arab Emirates\n"
        "   - 'S. Korea' / 'South Korea' -> South Korea\n"
        "   - 'Ivory Coast' / \"Côte d'Ivoire\" -> Ivory Coast\n"
        "  Apply this same normalization to every real country, not just "
        "the five shown above — never leave the country field null just "
        "because the exact spelling/punctuation looks unfamiliar, as "
        "long as it plausibly names a real country.\n"
        f"{_attr_route.RULE_TEXT if attr_on else ''}"
    )
    session_block = (
        f"SESSION HINT: {session_hint}\n" if session_hint else "SESSION HINT: none (cold start)\n"
    )
    user = f"{session_block}USER MESSAGE:\n{question}\n"

    def _call() -> tuple[str, int, int]:
        return _pinned_chat(sys, user, model_id, workspace_id)

    text, pt, ct = "", 0, 0
    # Hard timeout — escape hatch for the orchestrator. Deliberately not a
    # `with ThreadPoolExecutor() as pool:` block: __exit__ calls
    # shutdown(wait=True) as soon as the block is left for ANY reason,
    # including via fut.result()'s own TimeoutError, so the "timeout"
    # still blocks this call until the orphaned task actually finishes —
    # confirmed live (see classify_intent's _classify_with_timeout, same
    # fix). shutdown(wait=False) below lets it finish/GC in the
    # background instead.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = submit_ctx(pool, _call)
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
    finally:
        pool.shutdown(wait=False)

    raw = _parse_json_object(text)
    parsed = _parse_route(raw, allow_attribute_search=attr_on)
    if parsed is None:
        # One schema retry
        try:
            text2, pt2, ct2 = _pinned_chat(
                sys + "\nPREVIOUS OUTPUT INVALID. Return valid JSON only.\n",
                user, model_id, workspace_id,
            )
            pt += pt2
            ct += ct2
            parsed = _parse_route(
                _parse_json_object(text2), allow_attribute_search=attr_on,
            )
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
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8 shadow-logging work
    # (2026-09-29) discovered this branch is UNREACHABLE dead code: the
    # pre-LLM veto above already returns whenever `hard_off_topic(question)`
    # is true, using the exact same unmodified `question` value -- so by
    # the time this line runs, hard_off_topic(question) can only ever be
    # False. Confirmed empirically (a shadow-log placed here in this same
    # investigation never fired across multiple real off-topic-term test
    # messages) before this comment was written, not assumed. Left
    # unfixed/unremoved here deliberately -- removing or "fixing" it is
    # itself a live-routing-relevant decision (is a second post-LLM check
    # intentional defense-in-depth that's just currently broken, or truly
    # redundant with the pre-LLM veto?) that needs its own investigation,
    # out of scope for a shadow-logging-only pass.
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
        llm_cpq = map_route_to_det_expectation(parsed.route)
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
        "model=%s tokens=(%d,%d) attr=(%r,%r) rationale=%r",
        run_id, parsed.route, parsed.confidence, det_is_cpq, parsed.agreement,
        model_id, pt, ct, parsed.attribute_label, parsed.attribute_value,
        parsed.rationale,
    )
    return parsed


def map_route_to_det_expectation(route: AskRoute) -> bool:
    """Whether the deterministic is_cpq_question auditor should be True."""
    return route in ("quote", "ambiguous", _attr_route.ATTRIBUTE_SEARCH)
