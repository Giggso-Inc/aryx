"""Deterministic-detector agreement checks for mutating intent categories.

Split out of `cpq/intent_gateway.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Neither function calls `get_settings()`/`_pinned_chat` — they
only call `engine.detect_*()` methods on the `engine` object passed in by
the caller — so no patch-retargeting risk (confirmed via grep).
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.intent_schema.intent_schema import GatewayIntentResult, IntentCategory
from aryx.cpq.state import CpqSession, ConfigAttr

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
    # ISSUE-002 fix (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md),
    # revised per PR #205 review (High finding #2): DECLINE has no
    # `variable_name` at all (a pure session-state transition, not a
    # catalog attribute target), so `_mutating_agrees` special-cases it to
    # check the real boolean regex detector `detect_decline` instead of
    # the variable_name-matching logic every other member of this set
    # uses. APPROVAL is deliberately NOT in this set: the LLM was already
    # correctly classifying genuine approvals before this fix (that was
    # never the bug) — requiring `detect_approval()`'s hand-written regex
    # to also positively agree would reject any approval phrasing the LLM
    # correctly recognizes but the regex doesn't happen to cover, trading
    # the decline-misdispatch bug for a new false-negative-on-approval
    # bug. Instead, `_mutating_agrees` applies a DECLINE-only veto to
    # APPROVAL below (real conflict signal in one direction only), not a
    # requirement for positive agreement in the other.
    IntentCategory.DECLINE,
})


def _deterministic_mutating_signals(
    engine: Any,
    question: str,
    attrs: list[ConfigAttr],
    session: CpqSession,
    hiding_rules: list | None = None,
    rec_rules: list | None = None,
    con_rules: list | None = None,
    bml_eval: Any = None,
    workspace_id: int = 1,
    catalog_prefix: str = "",
) -> dict[str, set[str]]:
    """Map mutating category → set of variable_names detectors found.

    docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2b
    follow-up: ATTR_CLEAR / ATTR_ACTIVATION need rec_rules / hiding_rules
    / bml_eval to probe for real — previously left permanently empty
    ("so disagreement forces clarify rather than a half-blind
    agreement"), which meant `_mutating_agrees` returned False almost
    unconditionally for these two categories no matter what the LLM
    said, so `_gw.action` essentially never reached "dispatch" for
    them. Cost/impact confirmed cheap before wiring this: no new LLM
    call (the classification call already happened by this point
    regardless), only runs on a genuine cache miss (a cache hit returns
    before this function is ever called at all), and only during
    review-stage turns (this whole gateway's one call site is gated on
    `session.status in ("awaiting_approval", "post_approval")`).
    `hiding_rules`/`rec_rules`/`bml_eval` are optional (default `None`)
    so any other caller that doesn't have them yet keeps working
    unchanged — activation/clear probing is simply skipped (empty sets,
    same as before) when they're not supplied, never guessed.
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

    def _probe_activation() -> None:
        if hiding_rules is None:
            return
        activation = engine.detect_attr_activation(
            question, attrs, session.filled, session.filled_multi,
            hiding_rules, workspace_id, catalog_prefix, bml_eval=bml_eval,
        )
        if activation:
            out[IntentCategory.ATTR_ACTIVATION.value].add(activation.variable_name)

    def _probe_clear() -> None:
        if rec_rules is None or con_rules is None:
            return
        cleared = engine.detect_attr_clear(
            question, attrs, session.filled, rec_rules, con_rules, bml_eval=bml_eval,
            workspace_id=workspace_id, catalog_prefix=catalog_prefix,
        )
        if cleared:
            out[IntentCategory.ATTR_CLEAR.value].add(cleared.variable_name)

    _safe("change", _probe_change)
    _safe("removal", _probe_removal)
    _safe("bulk", _probe_bulk)
    _safe("activation", _probe_activation)
    _safe("clear", _probe_clear)
    return out


def _mutating_agrees(
    result: GatewayIntentResult,
    det_signals: dict[str, set[str]],
    last_qa_variables: list[str] | None = None,
    question: str = "",
    engine: Any = None,
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
    can never disambiguate; last_qa_variables is the only signal that can.
    A list, not a single value (docs/config_consistency_issues_2026-07-30.md
    Issue 12) — a compound options query can put more than one attribute
    into conversational recency at once.

    `question`/`engine` (ISSUE-002 fix, both default to a safe no-op value
    so every pre-existing call site that doesn't pass them keeps working
    unchanged — same "None keeps existing behavior unchanged" convention
    used everywhere else in this file): APPROVAL and DECLINE are pure
    session-state transitions with NO `variable_name` at all, so the
    variable_name-matching logic below (`if not result.variable_name:
    return False`) would always reject them if they fell through to it —
    naively adding them to MUTATING_CATEGORIES without this special case
    would silently break approval entirely. Checked FIRST, before any of
    the existing variable_name-based logic, which stays completely
    unchanged for every other category.
    """
    if result.intent_category == IntentCategory.DECLINE:
        return bool(engine is not None and engine.detect_decline(question))
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
    # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md review
    # finding (HIGH): the last_qa_variables shortcut below only makes sense
    # for value-bearing categories, where an independently-stated value
    # PLUS the just-discussed variable corroborate each other (neither
    # signal alone would be trustworthy, but together they are). Activation
    # and clear carry no value at all — the very thing that's unverified is
    # "is this really an activation/clear request," and conversational
    # recency says nothing about that question. Letting the shortcut apply
    # here would mean any ambiguous reply about a recently-discussed
    # attribute could silently activate or clear it with no real detector
    # confirmation at all. These two categories must always go through
    # their real deterministic detector.
    if result.intent_category in (
        IntentCategory.ATTR_ACTIVATION, IntentCategory.ATTR_CLEAR,
    ):
        return bool(det_vns) and result.variable_name in det_vns
    if last_qa_variables and result.variable_name in last_qa_variables:
        return True
    if not det_vns:
        # No deterministic hit at all — treat as disagreement so we clarify
        # rather than mutate solely on LLM word.
        return False
    return result.variable_name in det_vns
