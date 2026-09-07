"""Turn-intent detection/response cluster (Phase 4 step 2 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Re-exports every function so ``from aryx.cpq.turn_intent import <name>``
works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.turn_intent.patterns import (
    _APPROVAL_RE,
    _ARROW_RE,
    _BATCH_REQUEST_RE,
    _CHANGE_VERB_RE,
    _JSON_REQUEST_RE,
    _QA_INTENT_RE,
    _REMOVE_VERB_RE,
)
from aryx.cpq.turn_intent.patterns2 import (
    _ADD_VERB_RE,
    _ALLOWED_CHARS_RE,
    _BULK_QTY_RE,
    _CLEAR_VERB_RE,
    _DECLINE_RE,
    _GENERIC_CLAUSE_STOPWORDS,
    _MAX_MULTI_CHANGE_REQUESTS,
    _OPTIONS_KEYWORDS,
    _SHOW_SUMMARY_RE,
)
from aryx.cpq.turn_intent.response_state import (
    detect_approval,
    detect_decline,
    detect_qa_question,
    detect_response_mode_request,
    detect_show_summary_request,
)
from aryx.cpq.turn_intent.attr_toggle import detect_attr_activation, detect_multi_select_removal
from aryx.cpq.turn_intent.attr_clear_bulk import detect_attr_clear, detect_bulk_quantity_change
from aryx.cpq.turn_intent.change_targets_all import detect_all_change_targets_without_value
from aryx.cpq.turn_intent.change_request import (
    detect_change_request,
    detect_change_requests_multi,
    detect_change_target_without_value,
)
from aryx.cpq.turn_intent.unmatched_targets import detect_unmatched_change_targets
from aryx.cpq.turn_intent.match_candidate import _match_change_request_candidate
from aryx.cpq.turn_intent.matches import _change_request_matches
from aryx.cpq.turn_intent.cascade_review import build_review_prompt, find_cascade_dependents
from aryx.cpq.turn_intent.collision import detect_change_request_collision, detect_label_collision
from aryx.cpq.turn_intent.count_intents import count_turn_intents
from aryx.cpq.turn_intent.attr_query import detect_attr_query
from aryx.cpq.turn_intent.free_text import (
    _describe_char_allowlist,
    describe_free_text_constraint,
    should_ask_free_text_attr,
)
from aryx.cpq.turn_intent.labels import disambiguated_label
from aryx.cpq.turn_intent.next_question import next_question_prompt
from aryx.cpq.turn_intent.apply import apply_answer
from aryx.cpq.turn_intent.apply_multi import apply_multi_answer

__all__ = [
    "_JSON_REQUEST_RE",
    "_BATCH_REQUEST_RE",
    "_APPROVAL_RE",
    "_QA_INTENT_RE",
    "_CHANGE_VERB_RE",
    "_ARROW_RE",
    "_REMOVE_VERB_RE",
    "_ADD_VERB_RE",
    "_CLEAR_VERB_RE",
    "_BULK_QTY_RE",
    "_DECLINE_RE",
    "_GENERIC_CLAUSE_STOPWORDS",
    "_MAX_MULTI_CHANGE_REQUESTS",
    "_OPTIONS_KEYWORDS",
    "_SHOW_SUMMARY_RE",
    "_ALLOWED_CHARS_RE",
    "detect_response_mode_request",
    "detect_multi_select_removal",
    "detect_attr_activation",
    "detect_attr_clear",
    "detect_bulk_quantity_change",
    "detect_approval",
    "detect_decline",
    "detect_show_summary_request",
    "detect_qa_question",
    "detect_change_request",
    "detect_all_change_targets_without_value",
    "detect_change_target_without_value",
    "detect_change_requests_multi",
    "detect_unmatched_change_targets",
    "_match_change_request_candidate",
    "_change_request_matches",
    "find_cascade_dependents",
    "build_review_prompt",
    "detect_label_collision",
    "detect_change_request_collision",
    "count_turn_intents",
    "detect_attr_query",
    "_describe_char_allowlist",
    "describe_free_text_constraint",
    "should_ask_free_text_attr",
    "disambiguated_label",
    "next_question_prompt",
    "apply_answer",
    "apply_multi_answer",
]
