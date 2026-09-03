"""Gateway quarantine contract (LLM-first with candidate selection).

The intent gateway never lets the model invent catalog IDs or free-text
values. It selects from injected candidate lists only:
  variable_name ∈ candidate variable_names
  value_ref     = integer index into that attr's value candidates (or null)
  evidence_span = exact substring of the user question
Validated by parse_gateway_intent + validate_gateway_quarantine.

Split out of `cpq/intent_schema.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aryx.cpq.intent_schema_enums import Confidence, IntentCategory


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
