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
    APPROVAL = "approval"                               # detect_approval
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
    # BULK_QUANTITY_CHANGE only — the new quantity as stated, still a
    # plain string (e.g. "67"), not pre-parsed to int; the deterministic
    # resolver already owns numeric parsing/validation.
    quantity_description: str | None = None
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
    IntentCategory.RESPONSE_MODE_REQUEST,
    IntentCategory.QA_QUESTION,
    IntentCategory.OUT_OF_SCOPE,
    IntentCategory.AMBIGUOUS,
    IntentCategory.PRODUCT_MENTION,
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

    return GatewayIntentResult(
        intent_category=category,
        confidence=confidence,
        variable_name=vn,
        value_ref=value_ref,
        evidence_span=evidence,
        clarifying_question=clarifying,
        rationale=str(raw.get("rationale") or ""),
    )


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
    else:
        # No-target categories must not smuggle a hallucinated variable_name
        # that isn't in the candidate list (null is fine).
        if result.variable_name and result.variable_name not in candidate_vns:
            return _ambiguous("variable_name_not_in_candidates")

    return result
