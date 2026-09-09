"""Plain-language IntentResult contract — the two-layer classifier's
non-quarantined result shape (not wired into the live turn flow yet).

Split out of `cpq/intent_schema.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aryx.cpq.intent_schema.intent_schema_enums import Confidence, IntentCategory


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
