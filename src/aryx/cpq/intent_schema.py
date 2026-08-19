"""Phase 0 deliverable — docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

Structured intent-classification contract for the planned LLM-first
classifier. Defines WHAT the LLM is asked to return per turn — never a
raw catalog identifier (variable_name/item_value/entity_id), only
plain-language target descriptions the deterministic resolution layer
(existing detect_*/apply_answer functions in engine.py) resolves
afterward. See the plan doc §5 for the two-layer rationale.

Not wired into the live turn flow yet (that starts at Phase 1 — shadow
mode). This module is the schema only: a JSON-Schema dict for the
structured-output LLM call, plus a matching dataclass for the parsed,
validated result. Both must be kept in sync — `INTENT_RESULT_JSON_SCHEMA`
is what the model is constrained to produce; `IntentResult` is what the
rest of the codebase consumes after `parse_intent_result` validates it.

Category note (plan doc §5 refinement): `label_collision` and
`change_request_collision` are deliberately NOT categories here. Under
the two-layer design, "the target is ambiguous because 2+ real attrs
match" is something the DETERMINISTIC resolution layer discovers when it
tries to resolve a `target_description` — not something the LLM decides
upfront. Folding them into the classifier would require the LLM to know
about catalog-specific label collisions in advance, which defeats the
whole point of it working from plain language. They surface downstream
as a resolution-layer AMBIGUOUS outcome instead (see `AMBIGUOUS` category
below, and the "resolution failure" path in the plan doc's mitigation
table, risk #4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class IntentCategory(str, Enum):
    """One entry per existing deterministic detector in engine.py, mapped
    1:1 so an IntentResult can be dispatched to the SAME existing handler
    functions (_handle_cascade, _handle_multi_select_removal, etc.) the
    regex path already uses — see plan doc §5 point 4.
    """

    PRODUCT_MENTION = "product_mention"                # detect_product_mention
    RESPONSE_MODE_REQUEST = "response_mode_request"     # detect_response_mode_request
    MULTI_SELECT_REMOVAL = "multi_select_removal"       # detect_multi_select_removal
    ATTR_ACTIVATION = "attr_activation"                 # detect_attr_activation
    ATTR_CLEAR = "attr_clear"                           # detect_attr_clear
    BULK_QUANTITY_CHANGE = "bulk_quantity_change"       # detect_bulk_quantity_change
    # The OVERALL order/product quantity (a session-level virtual field,
    # never a real catalog attribute — quantity_turn_precheck/
    # extract_quantity_hint own the deterministic side). Added 2026-08-13:
    # this category never existed before, so the LLM had no way to even
    # express "the customer wants to change the overall quantity" — every
    # configuring-stage quantity change was decided by regex alone, with
    # no LLM confirmation possible even in principle. See docs/
    # CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md follow-up.
    PRODUCT_QUANTITY_CHANGE = "product_quantity_change"
    # The session-level shipping/destination country hint (session.country),
    # never a real catalog attribute -- mirrors PRODUCT_QUANTITY_CHANGE's
    # reasoning exactly. Added 2026-08-13 follow-up: detect_country_change_
    # request owns the deterministic side; before this category existed,
    # an explicit "change country to X" command had no way to be classified
    # at all and fell through to generic attribute disambiguation instead.
    COUNTRY_CHANGE = "country_change"
    APPROVAL = "approval"                               # detect_approval
    # Explicit rejection of an awaiting-approval configuration — added
    # 2026-08-17 (ISSUE-002, docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_
    # PLAN_2026_08_17.md). Before this category existed, an explicit "no,
    # decline that" had nowhere to land other than APPROVAL/AMBIGUOUS, and
    # since APPROVAL was excluded from the deterministic cross-check every
    # other mutating category gets, a confident-but-wrong LLM "approval"
    # classification of decline language dispatched straight to the BOM
    # approval handler. Maps to the new detect_decline detector (engine.py,
    # _DECLINE_RE, next to detect_approval).
    DECLINE = "decline"                                 # detect_decline
    QA_QUESTION = "qa_question"                         # detect_qa_question
    CHANGE_REQUEST = "change_request"                   # detect_change_request
    CHANGE_TARGET_WITHOUT_VALUE = "change_target_without_value"  # detect_change_target_without_value
    CHANGE_REQUESTS_MULTI = "change_requests_multi"     # detect_change_requests_multi
    ATTR_QUERY = "attr_query"                           # detect_attr_query
    # Not a regex-detector mirror — the classifier's own explicit "I'm not
    # sure" signal, required whenever confidence is low OR no category
    # above plausibly fits. This is the "ask before guessing, even for a
    # single word" behavior from the owner's original request.
    AMBIGUOUS = "ambiguous"
    # Mirrors the existing _llm_classify_is_cpq_question negative case —
    # the question is not about product configuration/quoting at all.
    OUT_OF_SCOPE = "out_of_scope"
    # First-class undo — restore last CpqSession snapshot from history[]
    # (session_guard). Not a regex cascade detector; handled before
    # LLM-first dispatch in ask_api.
    UNDO = "undo"
    # A question ABOUT the conversation/process itself ("what's next?",
    # "where am I?", "what should I do now?") -- never about catalog
    # content. Added 2026-08-18 (docs/CPQ_QA_RESUME_CONCATENATION_PLAN_
    # 2026_08_18.md): _handle_cpq_qa's generic graph-QA path has zero
    # awareness of what's still pending, so a bare meta-question like this
    # was hallucinating an irrelevant catalog answer glued to the correct
    # "Resuming your configuration..." reminder. When something is
    # genuinely pending, the pending question itself IS the answer to
    # "what's next" -- no graph knowledge needed. Not a regex-detector
    # mirror; replaced an earlier hardcoded phrase-list approach
    # specifically because a fixed list under-generalizes across phrasing
    # variants, the same "not a regex/deterministic pattern" reasoning
    # already applied to PRODUCT_QUANTITY_CHANGE elsewhere in this file.
    SESSION_STATUS_QUERY = "session_status_query"


class Confidence(str, Enum):
    """Three bands, not a raw float — matches the existing
    `_llm_resolve_pending_answer` convention ("high"/"low" confidence
    candidates) already used elsewhere in this codebase, rather than
    inventing a new numeric-threshold convention. LOW must always route
    to AMBIGUOUS handling regardless of category (plan doc mitigation #9)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ChangeTarget:
    """One (target, new value) pair, in plain language only — never a
    variable_name or item_value. Used directly by CHANGE_REQUEST and
    CHANGE_TARGET_WITHOUT_VALUE (single target), and as a list element
    for CHANGE_REQUESTS_MULTI and MULTI_SELECT_REMOVAL.

    `target_description` and `new_value_description` are handed to the
    EXISTING deterministic resolvers (`detect_attr_query`-style
    label/fragment matching, `apply_answer`/`apply_multi_answer`) which
    turn them into real catalog IDs — or report unresolvable, which the
    caller must treat as AMBIGUOUS (plan doc mitigation #1/#4), never as
    a fallback guess.
    """

    target_description: str
    new_value_description: str | None = None


@dataclass
class IntentResult:
    """Parsed, validated result of one classification call — the ONLY
    shape the rest of the codepath is allowed to consume. Constructed by
    `parse_intent_result`, never by hand-parsing raw LLM JSON at the call
    site (plan doc mitigation #7 — one shared parse/validate chokepoint).
    """

    category: IntentCategory
    confidence: Confidence
    # Populated for CHANGE_REQUEST, CHANGE_TARGET_WITHOUT_VALUE,
    # ATTR_ACTIVATION, ATTR_CLEAR, ATTR_QUERY, BULK_QUANTITY_CHANGE
    # (single-target categories). None for categories with no target
    # (APPROVAL, RESPONSE_MODE_REQUEST, QA_QUESTION, OUT_OF_SCOPE).
    target: ChangeTarget | None = None
    # Populated only for CHANGE_REQUESTS_MULTI and MULTI_SELECT_REMOVAL
    # (the only two categories a single message can name >1 target for —
    # matches detect_change_requests_multi's/detect_multi_select_removal's
    # own existing multi-target return shapes).
    targets: list[ChangeTarget] = field(default_factory=list)
    # RESPONSE_MODE_REQUEST only — mirrors detect_response_mode_request's
    # "json" | "batch" return value.
    response_mode: str | None = None
    # BULK_QUANTITY_CHANGE and PRODUCT_QUANTITY_CHANGE only — the new
    # quantity as stated, still a plain string (e.g. "67"), not
    # pre-parsed to int; the deterministic resolver already owns numeric
    # parsing/validation.
    quantity_description: str | None = None
    # COUNTRY_CHANGE only — the destination country as stated, already
    # validated by validate_gateway_quarantine (is_recognized_country)
    # before this dataclass is ever constructed. Added docs/CPQ_LLM_
    # INTENT_FIRST_UNIVERSAL_PLAN.md §8 Phase 4.
    country_description: str | None = None
    # Required whenever category == AMBIGUOUS: what to ask the user.
    # Also set by the caller (not the LLM) when the deterministic
    # resolution layer itself fails to resolve a HIGH-confidence target —
    # see plan doc mitigation #4 for why "ask, don't guess" must be the
    # resolver's own default, not something the LLM has to anticipate.
    clarifying_question: str | None = None
    # One-line justification, logged for shadow-mode analysis (Phase 1) —
    # never shown to the customer.
    rationale: str = ""


# JSON Schema the LLM's structured-output call is constrained to produce.
# Kept as a plain dict (not a third-party schema library) — matches this
# codebase's existing convention of hand-rolled JSON parsing in every
# `_llm_*` function (ask_api.py), just centralized and schema-validated
# instead of ad hoc per call site (plan doc mitigation #7).
INTENT_RESULT_JSON_SCHEMA: dict = {
    "type": "object",
    "required": ["category", "confidence", "rationale"],
    "properties": {
        "category": {
            "type": "string",
            "enum": [c.value for c in IntentCategory],
        },
        "confidence": {
            "type": "string",
            "enum": [c.value for c in Confidence],
        },
        "target": {
            "type": ["object", "null"],
            "properties": {
                "target_description": {"type": "string"},
                "new_value_description": {"type": ["string", "null"]},
            },
            "required": ["target_description"],
        },
        "targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_description": {"type": "string"},
                    "new_value_description": {"type": ["string", "null"]},
                },
                "required": ["target_description"],
            },
        },
        "response_mode": {"type": ["string", "null"], "enum": ["json", "batch", None]},
        "quantity_description": {"type": ["string", "null"]},
        "clarifying_question": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
}


def parse_intent_result(raw: dict) -> IntentResult | None:
    """Validate + construct an IntentResult from raw parsed LLM JSON, or
    None on any schema violation — fail-closed, same convention every
    existing `_llm_*` function in ask_api.py already follows (return
    None/False on anything unparseable rather than guessing a shape).

    Deliberately conservative: a category value outside the known enum,
    or AMBIGUOUS without a clarifying_question, is treated as a parse
    failure, not silently coerced — callers must have exactly one shared
    place that can reject a malformed classification (plan doc
    mitigation #7), not each call site inventing its own leniency.
    """
    try:
        category = IntentCategory(raw["category"])
        confidence = Confidence(raw["confidence"])
    except (KeyError, ValueError):
        return None

    if category == IntentCategory.AMBIGUOUS and not raw.get("clarifying_question"):
        return None

    target = None
    if raw.get("target"):
        t = raw["target"]
        if not isinstance(t, dict) or "target_description" not in t:
            return None
        target = ChangeTarget(
            target_description=t["target_description"],
            new_value_description=t.get("new_value_description"),
        )

    targets: list[ChangeTarget] = []
    for t in raw.get("targets") or []:
        if not isinstance(t, dict) or "target_description" not in t:
            return None
        targets.append(ChangeTarget(
            target_description=t["target_description"],
            new_value_description=t.get("new_value_description"),
        ))

    return IntentResult(
        category=category,
        confidence=confidence,
        target=target,
        targets=targets,
        response_mode=raw.get("response_mode"),
        quantity_description=raw.get("quantity_description"),
        clarifying_question=raw.get("clarifying_question"),
        rationale=str(raw.get("rationale", "")),
    )


# ── Gateway quarantine contract (LLM-first with candidate selection) ──────────
# The intent gateway never lets the model invent catalog IDs or free-text
# values. It selects from injected candidate lists only:
#   variable_name ∈ candidate variable_names
#   value_ref     = integer index into that attr's value candidates (or null)
#   evidence_span = exact substring of the user question
# Validated by parse_gateway_intent + validate_gateway_quarantine.


@dataclass
class GatewayIntentResult:
    """Parsed LLM gateway result — selection-only fields, no free-text IDs."""

    intent_category: IntentCategory
    confidence: Confidence
    variable_name: str | None = None
    value_ref: int | None = None
    # BULK_QUANTITY_CHANGE only — the new quantity as stated by the user,
    # a free-form digits-only string (e.g. "67"). Not a candidate-list
    # selection, so it can't be expressed via value_ref like every other
    # category's value — docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md
    # Phase 4. Null for every other category.
    quantity_text: str | None = None
    # RESPONSE_MODE_REQUEST only — "json" | "batch" | None, mirrors
    # detect_response_mode_request's own return value. Null for every
    # other category.
    response_mode: str | None = None
    # COUNTRY_CHANGE only — the destination country as stated by the
    # user, plain text (e.g. "United States"), validated against
    # CpqEngine.is_recognized_country before being trusted (same
    # quarantine discipline as quantity_text). Added docs/CPQ_LLM_
    # INTENT_FIRST_UNIVERSAL_PLAN.md §8 Phase 4. Null for every other
    # category.
    country_text: str | None = None
    evidence_span: str = ""
    clarifying_question: str | None = None
    rationale: str = ""


GATEWAY_INTENT_JSON_SCHEMA: dict = {
    "type": "object",
    "required": [
        "intent_category", "confidence", "variable_name",
        "value_ref", "evidence_span",
    ],
    "properties": {
        "intent_category": {
            "type": "string",
            "enum": [c.value for c in IntentCategory],
        },
        "confidence": {
            "type": "string",
            "enum": [c.value for c in Confidence],
        },
        "variable_name": {
            "type": ["string", "null"],
            "description": (
                "Exact variable_name from the CANDIDATE ATTRIBUTES list, "
                "or null when the category has no attribute target."
            ),
        },
        "value_ref": {
            "type": ["integer", "null"],
            "description": (
                "0-based index into that attribute's VALUE CANDIDATES list. "
                "Never free text. Null when no value is named."
            ),
        },
        "quantity_text": {
            "type": ["string", "null"],
            "description": (
                "BULK_QUANTITY_CHANGE (a specific grid row's quantity) or "
                "PRODUCT_QUANTITY_CHANGE (the OVERALL order quantity) only "
                "-- the new quantity as stated by the user, converted to "
                "plain digits, optionally with a leading '-' for a "
                "genuinely negative quantity (e.g. \"67\", \"-5\"). "
                "Always resolve the FINAL numeric value yourself -- "
                "spelled-out numbers (\"one hundred and twelve\" -> "
                "\"112\"), compound/scaled phrases (\"half a dozen\" -> "
                "\"6\", \"a couple dozen\" -> \"24\", \"twenty twelve\" -> "
                "\"32\"), and a sign word before a digit (\"minus 5\" -> "
                "\"-5\") all resolve to ONE plain digit string -- never "
                "leave any of it as words. A product name or other words "
                "sitting between the number and a quantity word (\"15 APX "
                "NEXT radios\") does not change the answer -- extract 15 "
                "regardless of what's in between. Only set this when the "
                "user is actually STATING a quantity to change TO: never "
                "when a number merely appears inside a conditional/"
                "comparison clause (e.g. \"unless the quantity is 6\" is "
                "NOT a request to change the quantity to 6 -- it is a "
                "condition; classify that as ambiguous or whatever the "
                "sentence is actually asking for instead), and never a "
                "year, model number, or other unrelated count that "
                "happens to precede a noun (e.g. \"the 2026 model\" "
                "states no order quantity at all -- null here, even "
                "though \"model\" can otherwise be a quantity-context "
                "word). Null for every other category or when no "
                "quantity is genuinely stated."
            ),
        },
        "response_mode": {
            "type": ["string", "null"],
            "enum": ["json", "batch", None],
            "description": (
                "RESPONSE_MODE_REQUEST only -- \"json\" or \"batch\". Null "
                "for every other category."
            ),
        },
        "country_text": {
            "type": ["string", "null"],
            "description": (
                "COUNTRY_CHANGE only -- the destination country as stated "
                "by the user, plain text (e.g. \"United States\"). Set "
                "this whenever the user states a destination country for "
                "the order -- an explicit change command (\"change "
                "country to Canada\", \"set country to Canada\") AND a "
                "plain destination statement with no change verb at all "
                "(\"ship to Canada\", \"deliver to Canada\") both count "
                "equally; do not require change-framing wording. ALWAYS "
                "put the country here as plain text -- never select this "
                "via variable_name/value_ref instead, even when a "
                "similarly-named catalog attribute (e.g. an \"ultimate "
                "destination country\" field) appears in the candidate "
                "list; country_text is the one and only way to report a "
                "destination country. Never set this when a country name "
                "merely appears elsewhere in the message (e.g. describing "
                "where a customer is already located, or inside a "
                "conditional clause). Null for every other category."
            ),
        },
        "evidence_span": {
            "type": "string",
            "description": "Exact contiguous substring of the user question.",
        },
        "clarifying_question": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
}


# Categories that do not require a variable_name target.
_GATEWAY_NO_TARGET_CATEGORIES = frozenset({
    IntentCategory.APPROVAL,
    # Explicit rejection of an awaiting-approval configuration -- a pure
    # session-state transition, exactly like APPROVAL just above, with no
    # catalog attribute to select (ISSUE-002 fix, 2026-08-17).
    IntentCategory.DECLINE,
    IntentCategory.RESPONSE_MODE_REQUEST,
    IntentCategory.QA_QUESTION,
    IntentCategory.OUT_OF_SCOPE,
    IntentCategory.AMBIGUOUS,
    IntentCategory.PRODUCT_MENTION,
    # The overall product quantity is a session-level field, never a real
    # catalog attribute -- there is no variable_name to select here, only
    # a stated quantity (see the quantity_text check below).
    IntentCategory.PRODUCT_QUANTITY_CHANGE,
    # session.country is likewise session-level, not a catalog attribute --
    # no variable_name to select here either.
    IntentCategory.COUNTRY_CHANGE,
})


def parse_gateway_intent(raw: dict) -> GatewayIntentResult | None:
    """Fail-closed parse of one gateway structured-output payload."""
    try:
        category = IntentCategory(raw["intent_category"])
        confidence = Confidence(raw["confidence"])
    except (KeyError, ValueError, TypeError):
        return None

    vn = raw.get("variable_name")
    if vn is not None and not isinstance(vn, str):
        return None
    if vn == "":
        vn = None

    value_ref = raw.get("value_ref")
    if value_ref is not None:
        if isinstance(value_ref, bool) or not isinstance(value_ref, int):
            return None

    evidence = raw.get("evidence_span")
    if not isinstance(evidence, str):
        return None

    clarifying = raw.get("clarifying_question")
    if clarifying is not None and not isinstance(clarifying, str):
        return None
    if category == IntentCategory.AMBIGUOUS and not clarifying:
        return None

    quantity_text = raw.get("quantity_text")
    if quantity_text is not None and not isinstance(quantity_text, str):
        return None

    response_mode = raw.get("response_mode")
    if response_mode is not None and response_mode not in ("json", "batch"):
        return None

    country_text = raw.get("country_text")
    if country_text is not None and not isinstance(country_text, str):
        return None

    return GatewayIntentResult(
        intent_category=category,
        confidence=confidence,
        variable_name=vn,
        value_ref=value_ref,
        quantity_text=quantity_text,
        response_mode=response_mode,
        country_text=country_text,
        evidence_span=evidence,
        clarifying_question=clarifying,
        rationale=str(raw.get("rationale") or ""),
    )


_SIGNED_DIGITS_RE = re.compile(r"^-?\d+$")


def _is_signed_digit_quantity_text(qty: str | None) -> bool:
    """True for a plain (optionally negative) digit string -- "67", "-5"
    -- never a word/decimal/anything else. `str.isdigit()` alone rejects
    a leading "-", which would silently make it impossible for the
    quarantine to ever accept a genuinely negative quantity the LLM
    correctly extracted (e.g. "minus 5 units") -- the deterministic
    `extract_quantity_hint` path explicitly supports and returns
    negative values (validated downstream by `is_valid_product_
    quantity`, never here), so this quarantine must not be stricter
    than that path for the exact same shape of input."""
    return bool(qty and _SIGNED_DIGITS_RE.match(qty.strip()))


def validate_gateway_quarantine(
    result: GatewayIntentResult,
    question: str,
    candidate_vns: set[str],
    value_counts: dict[str, int],
) -> GatewayIntentResult:
    """Quarantine guardrails: illegal selection → AMBIGUOUS downgrade.

    Rejects when:
    - variable_name not in the injected candidate set (when a target is required)
    - value_ref out of range for that attribute's value list
    - evidence_span not found verbatim in the user question
    - confidence is LOW (always clarify rather than act)
    """
    def _ambiguous(reason: str) -> GatewayIntentResult:
        q = result.clarifying_question or (
            "I want to make sure I update the right field — which attribute "
            "and value did you mean?"
        )
        return GatewayIntentResult(
            intent_category=IntentCategory.AMBIGUOUS,
            confidence=Confidence.LOW,
            variable_name=None,
            value_ref=None,
            quantity_text=None,
            response_mode=None,
            evidence_span=result.evidence_span or "",
            clarifying_question=q,
            rationale=f"quarantine:{reason}; {result.rationale}".strip(),
        )

    if result.confidence == Confidence.LOW:
        return _ambiguous("low_confidence")

    span = result.evidence_span or ""
    if span and span not in question:
        # case-insensitive fallback still requires contiguous chars present
        if span.lower() not in question.lower():
            return _ambiguous("evidence_span_missing")

    needs_target = result.intent_category not in _GATEWAY_NO_TARGET_CATEGORIES
    if needs_target:
        if not result.variable_name or result.variable_name not in candidate_vns:
            return _ambiguous("variable_name_not_in_candidates")
        n_vals = value_counts.get(result.variable_name, 0)
        if result.value_ref is not None:
            if result.value_ref < 0 or result.value_ref >= n_vals:
                return _ambiguous("value_ref_out_of_range")
        if result.intent_category == IntentCategory.BULK_QUANTITY_CHANGE:
            qty = result.quantity_text
            if not _is_signed_digit_quantity_text(qty):
                return _ambiguous("quantity_text_missing_or_invalid")
    else:
        # No-target categories must not smuggle a hallucinated variable_name
        # that isn't in the candidate list (null is fine).
        if result.variable_name and result.variable_name not in candidate_vns:
            return _ambiguous("variable_name_not_in_candidates")
        if (
            result.intent_category == IntentCategory.RESPONSE_MODE_REQUEST
            and result.response_mode not in ("json", "batch")
        ):
            return _ambiguous("response_mode_missing_or_invalid")
        if result.intent_category == IntentCategory.PRODUCT_QUANTITY_CHANGE:
            qty = result.quantity_text
            if not _is_signed_digit_quantity_text(qty):
                return _ambiguous("quantity_text_missing_or_invalid")
        if result.intent_category == IntentCategory.COUNTRY_CHANGE:
            # Lazy import — engine.py is a large module and this keeps the
            # schema module's own import graph light; no circularity risk
            # (engine.py never imports intent_schema).
            from aryx.cpq.engine import CpqEngine as _CpqEngine
            country = result.country_text
            if not country or not _CpqEngine.is_recognized_country(country):
                return _ambiguous("country_text_missing_or_unrecognized")

    return result
