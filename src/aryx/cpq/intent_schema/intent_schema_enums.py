"""Shared category/confidence enums for the LLM-first intent contract.

Split out of `cpq/intent_schema.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See intent_schema.py's module docstring for the two-layer
design context this enum serves.
"""
from __future__ import annotations

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
