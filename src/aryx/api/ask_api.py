"""Ask API — natural-language questions answered over the knowledge graph.

Flow: extract terms -> deterministic graph retrieval -> synthesise -> verify
grounding. Returns the answer, graph calls, usage, and the grounding record.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from aryx import llm_runtime
from aryx.api.ask_request_models import AskRequest, LlmConfigRequest, Turn
from aryx.api.ask_standard_pipeline import (
    _enforce_plain_answer,  # noqa: F401 — re-exported, see module docstring below
    _enrich_with_attributes,
    _extract_terms,
    _recent,
    _rewrite_plain,  # noqa: F401 — re-exported, see module docstring below
    _standard_ask_pipeline,
    _strip_think,
    _synthesise,
    _user_texts_from_history,
)
from aryx.config import get_settings
from aryx.cpq.engine import (
    CpqEngine, DECISION_REQUIRED_KEYS, SUMMARY_FALLBACK_CATEGORY, SUMMARY_CATEGORY_NAMES,
    MAX_PRODUCT_QUANTITY, MIN_PRODUCT_QUANTITY, detect_country_change_request,
    extract_quantity_hint, is_valid_product_quantity, question_mentions_quantity,
    quantity_turn_precheck, variable_name_words, _valid,
)
from aryx.cpq.bom_gate import (
    find_missing_required_fields, recheck_constraints, validate_before_payload,
)
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
    _is_signed_digit_quantity_text,
    parse_intent_result,
)
from aryx.cpq.logging_context import install_run_id_logging, set_run_id
from aryx.cpq import rule_trace
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
    ScopeResolve,
    candidates_from_attr_options,
    clear_pending_scope,
    format_did_you_mean,
    is_confident_scope_suggestion,
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




# Moved to ask_cpq_summary_text.py (Phase 3/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_cpq_summary_text import _cpq_summary_text  # noqa: E402



# Moved to ask_llm_catalog_enumeration.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_llm_catalog_enumeration import _llm_detect_catalog_enumeration_query  # noqa: E402


# Moved to ask_catalog_listing_text.py (Phase 3/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_catalog_listing_text import _build_catalog_attribute_listing_text  # noqa: E402



# Moved to ask_llm_split_multi_attr_options.py/ask_llm_split_multi_
# attr_change.py (Phase 6/11-phase ask_api decomposition) -- re-exported
# here so every existing caller/test keeps working unchanged.
from aryx.api.ask_llm_split_multi_attr_change import (  # noqa: E402
    _llm_split_multi_attr_change_request,
)
from aryx.api.ask_llm_split_multi_attr_options import (  # noqa: E402
    _llm_split_multi_attr_options_query,
)



# Moved to ask_handle_cpq_qa.py (Phase 8/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_cpq_qa import _handle_cpq_qa  # noqa: E402



# Moved to ask_build_no_value_response.py (Phase 3/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_build_no_value_response import _build_no_value_response  # noqa: E402



# Moved to ask_llm_classify_scope_reply.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_llm_classify_scope_reply import _llm_classify_scope_reply  # noqa: E402





# Moved to ask_data_table_conflict_reask.py/ask_pending_exclusion.py/
# ask_singleton_pending.py/ask_stale_constraint_reask.py (Phase 4/11-
# phase ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_data_table_conflict_reask import (  # noqa: E402
    _reask_confirmed_data_table_conflict,
)
from aryx.api.ask_pending_exclusion import (  # noqa: E402
    _hard_exclude_from_pending, _NEVER_ASK_RECOMMENDED_ONLY_VNS,
)
from aryx.api.ask_singleton_pending import _auto_resolve_singleton_pending  # noqa: E402
from aryx.api.ask_stale_constraint_reask import (  # noqa: E402
    _reask_stale_constraint_violations,
)




# Moved to ask_invalidate_stale_base_model.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_invalidate_stale_base_model import (  # noqa: E402
    _BASE_MODEL_TRIGGER_VNS,
    _BASE_MODEL_VN,
    _invalidate_stale_base_model,
)


# Moved to ask_handle_cascade.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_cascade import _handle_cascade  # noqa: E402


# Moved to ask_handle_multi_select_removal.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_multi_select_removal import _handle_multi_select_removal  # noqa: E402


# Moved to ask_handle_attr_activation.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_attr_activation import _handle_attr_activation  # noqa: E402


# Moved to ask_handle_attr_clear.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_attr_clear import _handle_attr_clear  # noqa: E402


# Moved to ask_build_show_summary_response.py (Phase 3/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_build_show_summary_response import _build_show_summary_response  # noqa: E402


# Moved to ask_handle_bulk_quantity_change.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_bulk_quantity_change import _handle_bulk_quantity_change  # noqa: E402


# Moved to ask_handle_cascade_multi.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_cascade_multi import _handle_cascade_multi  # noqa: E402


# Moved to ask_relevant_intent_candidates.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_relevant_intent_candidates import (  # noqa: E402
    _LLM_INTENT_ATTRS_CAP_HARD, _LLM_INTENT_RELEVANT_CAP, _WORD_RE,
)

# Moved to ask_relevant_intent_candidates.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_relevant_intent_candidates import _relevant_intent_candidates  # noqa: E402


# Moved to ask_llm_resolve_pending_answer.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_llm_resolve_pending_answer import _llm_resolve_pending_answer  # noqa: E402


# Moved to ask_llm_intent_core.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_llm_intent_core import _llm_classify_intent_core  # noqa: E402


# Moved to ask_llm_classify_is_cpq_question.py (Phase 6/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_llm_classify_is_cpq_question import _llm_classify_is_cpq_question  # noqa: E402


# Moved to ask_llm_classify_is_ask_in_scope.py (Phase 6/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_llm_classify_is_ask_in_scope import _llm_classify_is_ask_in_scope  # noqa: E402


# Moved to ask_llm_extract_multi_attr_hints.py (Phase 6/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_llm_extract_multi_attr_hints import _llm_extract_multi_attr_hints  # noqa: E402




# Moved to ask_llm_classify_change_intent.py (Phase 6/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_llm_classify_change_intent import _llm_classify_change_intent  # noqa: E402


# ── Phase 1, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md — shadow-mode ──────
# universal intent classifier. NOT wired into any actual dispatch decision:
# called read-only, its result only ever reaches a log line, exactly like
# the Fix 4 `count_turn_intents` diagnostic this mirrors. See
# _shadow_classify_cpq_turn's docstring for the call site and guarantee.

# Moved to ask_llm_classify_intent_universal.py (Phase 6/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_llm_classify_intent_universal import _llm_classify_intent_universal  # noqa: E402


# Moved to ask_target_description.py (Phase 4/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test
# keeps working unchanged.
from aryx.api.ask_target_description import _resolve_target_description  # noqa: E402





# Moved to ask_gateway_to_intent_result.py (Phase 7/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_gateway_to_intent_result import _gateway_to_intent_result  # noqa: E402



# Moved to ask_dispatch_intent_result.py (Phase 7/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_dispatch_intent_result import _dispatch_intent_result  # noqa: E402


# Moved to ask_build_product_quantity_response.py (Phase 3/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_build_product_quantity_response import (  # noqa: E402
    _build_product_quantity_change_response,
)


# Moved to ask_build_country_change_response.py (Phase 3/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_build_country_change_response import _build_country_change_response  # noqa: E402


# Moved to ask_handle_llm_first_gateway_turn.py (Phase 7/11-phase
# ask_api decomposition) -- re-exported here so every existing caller/
# test keeps working unchanged.
from aryx.api.ask_handle_llm_first_gateway_turn import _llm_first_gateway_turn  # noqa: E402




# Moved to ask_handle_approval.py (Phase 5/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_handle_approval import _handle_approval  # noqa: E402






# ── Gateway clarify memory (pending_clarify_*) ───────────────────────────────
# Live gap: "change hardware" → clarify "Hardware Version or System Key?" →
# reply "Hardware Version" had no pending state and fell to the review nudge.

# Moved to ask_pending_clarify_apply.py/ask_pending_clarify_grounding.py/
# ask_pending_clarify_llm_classify.py/ask_pending_clarify_prompt.py
# (Phase 2/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_pending_clarify_apply import (  # noqa: E402
    _apply_pending_clarify_resolution, _clear_pending_clarify,
)
from aryx.api.ask_pending_clarify_grounding import _ground_clarify_candidates  # noqa: E402
from aryx.api.ask_pending_clarify_llm_classify import (  # noqa: E402
    _llm_classify_pending_clarify_reply,
)
from aryx.api.ask_pending_clarify_prompt import _grounded_clarify_prompt  # noqa: E402



# Moved to ask_pending_clarify_match.py/ask_pending_clarify_turn.py
# (Phase 2/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_pending_clarify_match import (  # noqa: E402
    _match_pending_clarify_reply, _reply_matches_attr_option,
)
from aryx.api.ask_pending_clarify_turn import _handle_pending_clarify_turn  # noqa: E402



# Moved to ask_pending_clarify_answer.py (Phase 2/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_pending_clarify_answer import _set_pending_clarify_and_answer  # noqa: E402


def _run_cpq_turn(
    req: AskRequest, reader: Any, route_meta: "AskRouteDecision | None" = None,
) -> dict[str, Any]:
    """Execute one turn of the 8-step CPQ guided-configuration conversation.

    route_meta — the top-level router's decision, when this is the very
    first turn of a brand-new session (never populated for turn 2+, since
    the live-session path in `run_ask` never calls the router at all).
    docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md turn-1 unified
    extraction plan: carries `quantity`/`country` extracted by that SAME
    router call, threaded through to seed the turn before Step 1 runs.

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

    docs/CPQ_Usage_Reporting_Gap — this is the single choke point every
    internal CPQ code path converges through, so it's also where real
    per-turn LLM usage is reported. llm_runtime.reset_turn_usage() starts
    a fresh accumulator scoped to this request (ContextVar, safe under
    concurrent requests); llm_runtime.chat() — the one function every LLM
    call anywhere in the codebase already goes through, BML Tier-2 script
    evaluation included — adds into it automatically. If anything real
    happened this turn, _apply_real_llm_usage replaces whichever
    hardcoded "cpq-engine, 0 tokens" placeholder the internal handler
    returned with the real totals, instead of patching each of the
    dozens of individual response-construction blocks by hand.
    """
    llm_runtime.reset_turn_usage()
    result = enforce_conversational_invariant(_run_cpq_turn_inner(req, reader, route_meta))
    _apply_real_llm_usage(result)
    return result



# Moved to ask_turn_product_switch_anchor.py/ask_step1_product_anchor.py/
# ask_turn_intent_diagnostics.py/ask_turn_seed_product_anchor.py (Phase
# 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step1_product_anchor import _step1_resolve_product_anchor  # noqa: E402
from aryx.api.ask_turn_intent_diagnostics import _log_turn_intent_diagnostics  # noqa: E402
from aryx.api.ask_turn_product_switch_anchor import (  # noqa: E402
    _handle_product_switch_pending_anchor,
)
from aryx.api.ask_turn_seed_product_anchor import _seed_product_select_from_anchor  # noqa: E402
# Moved to ask_step678_review_status.py + sibling ask_step678_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step678_review_status import _handle_review_status_routing  # noqa: E402
from aryx.api.ask_model_leaf_resolve import _resolve_model_leaf  # noqa: E402
# Moved to ask_step2_resolve_and_load.py + sibling ask_step2_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step2_resolve_and_load import _step2_resolve_and_load  # noqa: E402
# Moved to ask_step8_pre_step5_gates.py + sibling ask_step8_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step8_pre_step5_gates import _step8_run_pre_step5_gates  # noqa: E402
# Moved to ask_step9_lock_pending_answer.py + sibling ask_step9_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step9_lock_pending_answer import _step9_lock_pending_answer  # noqa: E402
# Moved to ask_step10_rule_eval_loop.py + sibling ask_step10_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step10_rule_eval_loop import _step10_run_rule_eval_loop  # noqa: E402
# Moved to ask_step11_build_response.py + sibling ask_step11_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_step11_build_response import _step11_build_turn_response  # noqa: E402
from aryx.api.ask_turn_switch_redetect import _check_mid_turn_switch_redetection  # noqa: E402
# Moved to ask_preamble_run.py + sibling ask_preamble_*.py files
# (Phase 10/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_preamble_run import _preamble_run  # noqa: E402
# Moved to ask_core_helpers.py (final sweep, Phase 11/11-phase ask_api
# decomposition) -- re-exported here so every existing caller/test keeps
# working unchanged.
from aryx.api.ask_core_helpers import (  # noqa: E402
    _CPQ_SEGMENT_DELIM,
    _SENTENCE_SPLIT,
    _current_turn_usage_dict,
    _mine_history_for_cpq_context,
    _persist_cpq_history,
    _reader,
    _safe_detect_product_mention,
    _validate_workspace,
)
# Moved to ask_attr_text_helpers.py (final sweep, Phase 11/11-phase
# ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_attr_text_helpers import (  # noqa: E402
    _build_attr_options_text,
    _build_current_quote_attribute_listing_text,
    _resolve_split_change_text,
)
# Moved to ask_intent_queue_text_helpers.py (final sweep, Phase 11/11-
# phase ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_intent_queue_text_helpers import (  # noqa: E402
    _append_unmatched_targets_note,
    _apply_intent_conservation,
    _queue_followup_note,
    _scan_and_enqueue_remaining_targets,
)
# Moved to ask_change_decline_and_scope_memory.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_change_decline_and_scope_memory import (  # noqa: E402
    _constrain_excluding_rejected,
    _extract_replacement_clause,
    _is_change_value_decline,
    _is_global_change_decline,
    _remember_attr_scope,
)
# Moved to ask_scope_reask_responses.py (final sweep, Phase 11/11-phase
# ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_scope_reask_responses import (  # noqa: E402
    _build_scope_family_only_response,
    _build_scope_skip_response,
    _resolve_scope_reply,
    _scoped_reask_response,
)
# Moved to ask_label_collision_detect_and_compose.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_label_collision_detect_and_compose import (  # noqa: E402
    _DECLINE_CHANGE_RE,
    _compose_disambiguation_question,
    _label_collision_for,
)
# Moved to ask_label_collision_prompt_and_narrow.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_label_collision_prompt_and_narrow import (  # noqa: E402
    _label_collision_prompt,
    _narrow_label_collision,
)
# Moved to ask_shadow_classify_and_confirm_intent.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_shadow_classify_and_confirm_intent import (  # noqa: E402
    _llm_confirm_deterministic_intent,
    _shadow_classify_cpq_turn,
)
# Moved to ask_llm_confirm_extract_quantity.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_confirm_extract_quantity import (  # noqa: E402
    _build_llm_call_failed_response,
    _llm_confirm_and_extract_quantity,
)
# Moved to ask_llm_confirm_extract_country.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_confirm_extract_country import (  # noqa: E402
    _GATEWAY_CALL_FAILURE_REASONS,
    _llm_confirm_and_extract_country,
)
# Moved to ask_attr_query_and_classify_usage.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_attr_query_and_classify_usage import (  # noqa: E402
    _build_attr_query_response,
    _with_classify_usage,
)
# Moved to ask_llm_resolve_quantity_target.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_resolve_quantity_target import (  # noqa: E402
    _QTY_LABEL_BOILERPLATE_WORDS,
    _llm_resolve_quantity_target,
    _quantity_message_might_name_candidate,
)
# Moved to ask_json_preview_and_decline.py (final sweep, Phase 11/11-
# phase ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_json_preview_and_decline import (  # noqa: E402
    _build_json_preview_response,
    _handle_decline,
)
# Moved to ask_llm_extract_quantity_and_country_reply.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_extract_quantity_and_country_reply import (  # noqa: E402
    _llm_extract_quantity,
    _llm_resolve_bare_country_reply,
)
# Moved to ask_llm_topic_switch_and_change_decline.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_topic_switch_and_change_decline import (  # noqa: E402
    _llm_detect_change_decline,
    _llm_detect_pending_topic_switch,
    _pending_reply_is_topic_switch,
)
# Moved to ask_decline_reply_and_label_collision_llm.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_decline_reply_and_label_collision_llm import (  # noqa: E402
    _LOOSE_DECLINE_HINT_RE,
    _is_decline_reply,
    _llm_resolve_label_collision,
)
# Moved to ask_llm_switch_reply_and_compound_split.py (final sweep,
# Phase 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_switch_reply_and_compound_split import (  # noqa: E402
    _llm_classify_switch_reply,
    _llm_split_compound_change_and_question,
)
# Moved to ask_llm_usage_and_new_request_detect.py (final sweep, Phase
# 11/11-phase ask_api decomposition) -- re-exported here so every
# existing caller/test keeps working unchanged.
from aryx.api.ask_llm_usage_and_new_request_detect import (  # noqa: E402
    _apply_real_llm_usage,
    _pending_reply_looks_like_new_request,
)


def _run_cpq_turn_inner(
    req: AskRequest, reader: Any, route_meta: "AskRouteDecision | None" = None,
) -> dict[str, Any]:
    """Inner CPQ turn body — see ``_run_cpq_turn`` for the step contract."""
    (
        _preamble_early_response, session, hints, _country_llm_call_failed,
        _incoming_pending_anchor,
    ) = _preamble_run(req, reader, route_meta)
    if _preamble_early_response is not None:
        return _preamble_early_response

    logger.info("cpq_step: mid_session_product_switch_gate enter run_id=%s", session.run_id)
    # Mid-session product-switch gate (Phase 10/11-phase ask_api
    # decomposition): moved to ask_turn_product_switch_anchor.py and
    # sibling ask_turn_*.py files -- logic unchanged, see those modules'
    # own docstrings.
    _switch_anchor_response = _handle_product_switch_pending_anchor(
        req, session, reader, hints,
    )
    if _switch_anchor_response is not None:
        return _switch_anchor_response
    # Whether the product was anchored BEFORE this turn — switch detection
    # must only run for messages sent to an already-anchored session,
    # never on the very message that anchored it.
    product_was_anchored = bool(session.product_name)
    # STEP 1 (Phase 10/11-phase ask_api decomposition): moved to
    # ask_step1_product_anchor.py -- logic unchanged, see that module's
    # own docstring.
    _step1_response = _step1_resolve_product_anchor(req, session, reader, hints)
    if _step1_response is not None:
        return _step1_response

    (
        _step2_early_response, attrs, catalog_prefix, hiding_rules, rec_rules,
        con_rules, validation_rules, bml_eval, negated_vns,
    ) = _step2_resolve_and_load(
        req, session, reader, hints, product_was_anchored, _country_llm_call_failed,
        _incoming_pending_anchor,
    )
    if _step2_early_response is not None:
        return _step2_early_response

    logger.info(
        "cpq_step: step6_7_8_routing_gate enter run_id=%s status=%s",
        session.run_id, session.status,
    )
    review_status_result = _handle_review_status_routing(
        req, session, attrs, reader, hints,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
    )
    if review_status_result is not None:
        return review_status_result

    _step8_early_response, mode_request = _step8_run_pre_step5_gates(
        req, session, attrs, reader, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix,
    )
    if _step8_early_response is not None:
        return _step8_early_response

    logger.info("cpq_step: step5_lock_answer_gate enter run_id=%s", session.run_id)
    _step9_early_response, pending_var = _step9_lock_pending_answer(
        req, session, attrs, hints, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, mode_request,
    )
    if _step9_early_response is not None:
        return _step9_early_response

    logger.info("cpq_step: step5b_blocked_removal_gate enter run_id=%s", session.run_id)
    (
        _step10_early_response, visible_attrs, filled, display_filled, pending,
        constrained_opts, rule_ids, dropped_note,
    ) = _step10_run_rule_eval_loop(
        req, session, attrs, hints, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, negated_vns, mode_request,
        pending_var,
    )
    if _step10_early_response is not None:
        return _step10_early_response

    return _step11_build_turn_response(
        req, session, attrs, hints, visible_attrs, filled, display_filled, pending,
        constrained_opts, rule_ids, dropped_note, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, mode_request,
    )
# or the session has already reached review/approval regardless of count.
from aryx.api.ask_finish_cpq_result import (  # noqa: E402
    _deterministic_cpq_gate, _finish_cpq_result, _route_quote,
)
from aryx.api.ask_route_qa import _route_ambiguous, _route_qa  # noqa: E402
from aryx.api.ask_run_ask import run_ask  # noqa: E402
from aryx.api.ask_attach_share_flags import _attach_share_flags  # noqa: E402
# Moved to ask_mandatory_block_splice.py (final sweep, Phase 11/11-phase
# ask_api decomposition) -- re-exported here so every existing
# caller/test keeps working unchanged.
from aryx.api.ask_mandatory_block_splice import (  # noqa: E402
    _CPQ_JSON_TRAILER_RE,
    _MANDATORY_HEADER,
    _MANDATORY_SECTION_RE,
    _NAMED_CATEGORY_BULLET_RE,
    _OTHER_SUMMARY_CATEGORY_HEADERS,
    _SHARE_READY_MIN_FILLED,
    _beautify_mandatory_block,
    _labels_already_shown,
    _splice_mandatory_block_into_summary,
)


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
