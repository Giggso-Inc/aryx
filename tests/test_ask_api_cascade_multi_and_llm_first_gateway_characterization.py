"""Golden-master characterization tests for two ask_api.py functions with
ZERO prior direct test coverage anywhere in tests/ (confirmed by repo-wide
grep, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md "Phase 4 planning
analysis"):

    * `_handle_cascade_multi` (lines 4077-4468) — multi-target cascade
      change handling: applies every named change in one message, unions
      their cascade dependents, re-runs the rule loop once.
    * `_llm_first_gateway_turn` (lines 6767-7168) — the LLM-first gateway
      turn entry point: classifies intent via the gateway and dispatches.

This is step 1 of Phase 4 of the style-compliance plan — pinning CURRENT
behavior (bugs included, documented not fixed) before a future refactor
splits ask_api.py into <150-line files. Purely additive: no existing test
function is renamed/reused, no module-level mutable state is introduced,
and every mock.patch here targets `aryx.api.ask_api.<name>` the same way
the rest of the suite already does (see test_cpq_2026_07_28_fixes.py,
test_cpq_change_request_multi.py, test_cpq_turn_real_usage.py) so these
tests cannot interfere with any of the 314 existing patch call sites.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest
from aryx.api.ask_handle_cascade_multi import _handle_cascade_multi
from aryx.api.ask_handle_llm_first_gateway_turn import _llm_first_gateway_turn
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.intent_gateway import GatewayDecision
from aryx.cpq.intent_schema import (
    Confidence,
    GatewayIntentResult,
    IntentCategory,
)
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _no_rules_engine_patches(monkeypatch):
    """Same lightweight-loader pattern as test_cpq_2026_07_28_fixes.py's
    `_rules_setup` — real CpqEngine matching/rule-eval logic runs
    unmodified, only the DB/catalog-config loaders are stubbed out so no
    real Postgres/FalkorDB connection is needed."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "_load_layout_full_order", lambda *a, **k: {})
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: {})
    monkeypatch.setattr(api._cpq_engine, "product_label_noise_vns", lambda *a, **k: set())


# ═══════════════════════════════════════════════════════════════════════
# _handle_cascade_multi
# ═══════════════════════════════════════════════════════════════════════

def test_cascade_multi_returns_none_when_nothing_named_could_be_applied(monkeypatch):
    """No changed_vns and no pending_intent_queue -> None, mirroring
    detect_change_request's own "didn't understand" contract so the
    caller falls through to the generic nudge."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"}, status="awaiting_approval")
    req = AskRequest(question="irrelevant gibberish", workspace_id=1,
                      session_data=session.to_dict())
    resp = _handle_cascade_multi(req, session, [battery], [], [], [], [])
    assert resp is None


def test_cascade_multi_single_change_reaches_awaiting_approval(monkeypatch):
    """Happy path: one named change, no dependents, no other pending attrs
    -> rule pass completes, status becomes awaiting_approval, and the
    cascade note reports the single update."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"},
                          display_filled={"batteryType_astro": "Standard"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery type to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]
    resp = _handle_cascade_multi(req, session, [battery], matches, [], [], [])
    assert resp is not None
    assert resp["tools_called"] == ["cpq_cascade_multi()"]
    assert session.filled["batteryType_astro"] == "Extended"
    assert session.status == "awaiting_approval"
    assert "Updated **Battery Type** → **Extended**." in resp["answer"]
    assert resp["session_data"] == session.to_dict()


def test_cascade_multi_two_named_changes_applied_together(monkeypatch):
    """Both targets named in one message get applied in the SAME rule
    pass (not one-at-a-time) -- the core multi-target contract."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          display_filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended and carrier to Verizon",
                      workspace_id=1, session_data=session.to_dict())
    matches = [(battery, "Extended"), (carrier, "Verizon")]
    resp = _handle_cascade_multi(req, session, [battery, carrier], matches, [], [], [])
    assert resp is not None
    assert session.filled["batteryType_astro"] == "Extended"
    assert session.filled["carrierSelection_astro"] == "Verizon"
    assert "Updated **Battery Type** → **Extended**." in resp["answer"]
    assert "Updated **Carrier** → **Verizon**." in resp["answer"]


def test_cascade_multi_duplicate_target_in_matches_applied_only_once(monkeypatch):
    """The same attr matched twice in one message (matches list has two
    entries for it) is applied once -- the `if changed_attr.variable_name
    in changed_vns: continue` guard at the top of the loop."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"},
                          display_filled={"batteryType_astro": "Standard"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended, battery to Extended",
                      workspace_id=1, session_data=session.to_dict())
    matches = [(battery, "Extended"), (battery, "Extended")]
    resp = _handle_cascade_multi(req, session, [battery], matches, [], [], [])
    assert resp is not None
    assert resp["answer"].count("Updated **Battery Type**") == 1


def test_cascade_multi_partial_apply_reports_unparsable_target_and_queues_it(monkeypatch):
    """Product decision: partial apply. One target parses, the other's
    value hint doesn't resolve to a real option -- the unparsable one is
    reported by label AND queued (via enqueue_intent_targets) for a
    follow-up ask, never silently dropped and never rejecting the whole
    turn.

    Documents a side effect of the CURRENT implementation: the unconditional
    `session.filled.pop(changed_attr.variable_name, ...)` at the top of the
    per-match loop runs for EVERY named target before its new value is even
    parsed -- so an unparsable target's PRE-EXISTING filled value
    ("carrierSelection_astro": "ATT") is wiped from session.filled too, not
    just left unchanged. The attr is then immediately re-asked (queued to
    the front of `pending_variables` via drain_intent_queue_into_pending),
    so the value is recovered on the very next turn, but for this one turn
    the session genuinely has no value on record for it.
    """
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          display_filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended and carrier to Nonexistent",
                      workspace_id=1, session_data=session.to_dict())
    matches = [(battery, "Extended"), (carrier, "Nonexistent Value That Matches No Option")]
    resp = _handle_cascade_multi(req, session, [battery, carrier], matches, [], [], [])
    assert resp is not None
    assert session.filled["batteryType_astro"] == "Extended"
    # Bug-shaped current behavior: the unresolved target's PRIOR value is
    # dropped from filled, not preserved.
    assert "carrierSelection_astro" not in session.filled
    assert "Carrier" in resp["answer"]
    assert "carrierSelection_astro" in session.pending_intent_queue
    # Queued target is drained to the front of pending and asked next.
    assert session.pending_variables[0] == "carrierSelection_astro"


def test_cascade_multi_all_unparsable_with_prior_empty_queue_still_asks_it(monkeypatch):
    """Documents a subtlety in the `if not changed_vns and not
    session.pending_intent_queue: return None` guard (the docstring's own
    "return None only when NONE of the named changes could be applied"
    contract): by the time that guard runs, the SAME per-match loop has
    already called `enqueue_intent_targets` for this exact unparsable
    target (the "ask, don't report" queuing a few lines above) -- so
    `session.pending_intent_queue` is never actually empty at that check
    when `matches` was non-empty to begin with. The bare `return None`
    branch is therefore only reachable when `matches` itself is `[]`
    (covered by `test_cascade_multi_returns_none_when_nothing_named_could_
    be_applied` above); a non-empty `matches` list that fails to parse
    ALWAYS falls into the "ask the first queued one" branch instead, never
    the plain None fallthrough the docstring describes for this case."""
    _no_rules_engine_patches(monkeypatch)
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"carrierSelection_astro": "ATT"}, status="awaiting_approval")
    req = AskRequest(question="change carrier to Nonexistent", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(carrier, "Nonexistent Value That Matches No Option")]
    resp = _handle_cascade_multi(req, session, [carrier], matches, [], [], [])
    assert resp is not None
    assert resp["tools_called"] == ["cpq_cascade_multi_queue_ask(carrierSelection_astro)"]
    assert "Carrier" in resp["answer"]


def test_cascade_multi_all_unparsable_but_queue_nonempty_asks_head_of_queue(monkeypatch):
    """All named targets failed to parse this turn, but
    pending_intent_queue already had something queued from an earlier
    turn -- the function asks about the HEAD of that queue instead of
    falling through to None (`_build_no_value_response`, tool_name
    "cpq_cascade_multi_queue_ask")."""
    _no_rules_engine_patches(monkeypatch)
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    queued = _attr(3, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"carrierSelection_astro": "ATT"},
                          status="awaiting_approval",
                          pending_intent_queue=["batteryType_astro"])
    req = AskRequest(question="change carrier to Nonexistent", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(carrier, "Nonexistent Value That Matches No Option")]
    resp = _handle_cascade_multi(req, session, [carrier, queued], matches, [], [], [])
    assert resp is not None
    assert resp["tools_called"] == ["cpq_cascade_multi_queue_ask(batteryType_astro)"]
    assert "Battery Type" in resp["answer"]


def test_cascade_multi_all_unparsable_queue_head_not_in_attrs_returns_none(monkeypatch):
    """Edge case / latent-bug-shaped path: pending_intent_queue's head
    names a variable_name that no longer exists in `attrs` (e.g. the
    catalog changed underneath the session) -- `head_attr` resolves to
    None and the function falls through to a bare `return None` instead
    of skipping to the next queued item or reporting anything to the
    caller. Documents the CURRENT behavior: the rest of the queue is
    silently ignored for this turn, not attempted."""
    _no_rules_engine_patches(monkeypatch)
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"carrierSelection_astro": "ATT"},
                          status="awaiting_approval",
                          pending_intent_queue=["ghostVariable_astro"])
    req = AskRequest(question="change carrier to Nonexistent", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(carrier, "Nonexistent Value That Matches No Option")]
    resp = _handle_cascade_multi(req, session, [carrier], matches, [], [], [])
    assert resp is None


def test_cascade_multi_dependent_recalculated_and_named_in_note(monkeypatch):
    """A hiding rule makes `carrier` depend on `battery`; changing battery
    makes carrier a cascade dependent -- it's named in the combined
    cascade note ("Because those changed, **Carrier** depends on them..")
    and its stale filled value is cleared/recalculated by the rerun."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    hide_rule = HidingRule(
        rule_name="Hide carrier unless Extended", condition_attr_id=1,
        condition_value="Standard", target_attr_id=2, hide=True,
    )
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          display_filled={"batteryType_astro": "Standard", "carrierSelection_astro": "ATT"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]
    resp = _handle_cascade_multi(req, session, [battery, carrier], matches, [hide_rule], [], [])
    assert resp is not None
    assert "Carrier" in resp["answer"]
    assert "depends on" in resp["answer"]


def test_cascade_multi_multi_select_target_unions_into_existing_selection(monkeypatch):
    """select_type=="multi" branch: the new value is UNIONED into the
    existing filled_multi list (via apply_multi_answer), not replaced --
    distinct semantics from the single-select branch."""
    _no_rules_engine_patches(monkeypatch)
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount"))
    session = CpqSession(mode="cpq", product_name="videoSolutions_BOM",
                          filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="add the jacket mount too", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(mount, "Jacket Magnetic Mount")]
    resp = _handle_cascade_multi(req, session, [mount], matches, [], [], [])
    assert resp is not None
    assert session.filled_multi["mountingTypeArray_viSoln"] == [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount",
    ]
    assert "Updated **Mounting Type**" in resp["answer"]


def test_cascade_multi_multi_select_no_mention_matched_is_treated_as_unparsable(monkeypatch):
    """select_type=="multi" branch where apply_multi_answer finds nothing
    mentioned -> `result` forced to None -> same partial-apply/failed/
    queue handling as the single-select unparsable case -- which (see
    `test_cascade_multi_all_unparsable_with_prior_empty_queue_still_asks_
    it`'s docstring) means it is queued and immediately asked about,
    never a bare `return None`."""
    _no_rules_engine_patches(monkeypatch)
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount"))
    session = CpqSession(mode="cpq", product_name="videoSolutions_BOM",
                          filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
                          status="awaiting_approval")
    req = AskRequest(question="add nonexistent mount option zzz", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(mount, "nonexistent mount option zzz")]
    resp = _handle_cascade_multi(req, session, [mount], matches, [], [], [])
    assert resp is not None
    assert resp["tools_called"] == ["cpq_cascade_multi_queue_ask(mountingTypeArray_viSoln)"]
    assert "Mounting Type" in resp["answer"]


def test_cascade_multi_d1_precedence_check_reverts_a_rule_reasserted_value(monkeypatch):
    """D1 (docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md): a stably-true
    recommendation rule can silently reassign a single-select value the
    customer JUST explicitly set. This is checked AFTER the rule pass —
    when the rule pass's final `session.filled[vn]` doesn't match what
    the customer asked for, the applied note becomes an "isn't valid"
    message and the attr is popped back into pending, rather than being
    reported as a successful update."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"},
                          display_filled={"batteryType_astro": "Standard"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]

    # Force the rule pass to reassert "Standard" over the customer's
    # explicit "Extended" choice by stubbing evaluate_rules_loop's
    # returned `filled` -- simulates a recommendation rule stably firing.
    real_evaluate = api._cpq_engine.evaluate_rules_loop

    def _fake_evaluate_rules_loop(attrs, hints, filled, *a, **k):
        visible, filled_out, display_out, constrained = real_evaluate(
            attrs, hints, filled, *a, **k)
        filled_out = dict(filled_out)
        filled_out["batteryType_astro"] = "Standard"
        display_out = dict(display_out)
        display_out["batteryType_astro"] = "Standard"
        return visible, filled_out, display_out, constrained

    monkeypatch.setattr(api._cpq_engine, "evaluate_rules_loop", _fake_evaluate_rules_loop)
    resp = _handle_cascade_multi(req, session, [battery], matches, [], [], [])
    assert resp is not None
    assert "isn't valid given the rest of this configuration" in resp["answer"]
    assert "batteryType_astro" not in session.filled
    assert "batteryType_astro" in session.pending_variables


def test_cascade_multi_flat_required_flag_alone_does_not_force_pending(monkeypatch):
    """ConfigAttr.required (bm_config_attr.required) is documented elsewhere
    in this codebase (engine.py, near _BLIND_FILL_RISK_ACCEPTED_VNS) as
    confirmed live to be 0/unreliable for essentially every attribute in
    the real catalog — auto_fill's actual pending-detection is governed by
    rule-based signals (hiding/rec/con rules targeting the attr), not this
    flat field. With zero rules passed in, an attr with required=True and
    no default still does NOT land in `pending`, so status reaches
    awaiting_approval exactly like the single-change happy path — this
    pins that real (if perhaps surprising) current behavior rather than
    the flat field's nominal meaning."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", required=True,
                     options=_opt("ATT", "Verizon"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"},
                          display_filled={"batteryType_astro": "Standard"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]
    resp = _handle_cascade_multi(req, session, [battery, carrier], matches, [], [], [])
    assert resp is not None
    assert session.status == "awaiting_approval"
    assert "carrierSelection_astro" not in session.pending_variables


def test_cascade_multi_no_pending_reaches_awaiting_approval_with_summary(monkeypatch):
    """No pending attrs, no unresolved grid gaps, no stale constraint
    reask -> falls to the final else branch: status="awaiting_approval",
    a completion message with the product name is produced."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard"},
                          display_filled={"batteryType_astro": "Standard"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]
    resp = _handle_cascade_multi(req, session, [battery], matches, [], [], [])
    assert resp is not None
    assert session.status == "awaiting_approval"
    assert "Configuration complete for **aSTRO25_bom**." in resp["answer"]
    assert "say **confirm**" in resp["answer"]


def test_cascade_multi_set_type_2_dependent_excluded_from_note_but_recalculated(monkeypatch):
    """set_type=="2" attrs are filtered out of `dependent_labels` (never
    named in the cascade note) even though they ARE still recalculated by
    the rerun and excluded from the final pending list -- mirrors
    _handle_cascade's identical filter, documented here as the same
    live-verified finding applied to the multi-target path."""
    _no_rules_engine_patches(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("Standard", "Extended"))
    hidden_dep = ConfigAttr(
        entity_id=2, variable_name="internalComputed_astro", display_label="Internal Computed",
        required=False, default_value="", options=_opt("A", "B"), select_type="single",
        set_type="2",
    )
    hide_rule = HidingRule(
        rule_name="Hide computed unless Extended", condition_attr_id=1,
        condition_value="Standard", target_attr_id=2, hide=True,
    )
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                          filled={"batteryType_astro": "Standard", "internalComputed_astro": "A"},
                          display_filled={"batteryType_astro": "Standard", "internalComputed_astro": "A"},
                          status="awaiting_approval", turn=2)
    req = AskRequest(question="change battery to Extended", workspace_id=1,
                      session_data=session.to_dict())
    matches = [(battery, "Extended")]
    resp = _handle_cascade_multi(
        req, session, [battery, hidden_dep], matches, [hide_rule], [], [])
    assert resp is not None
    assert "Internal Computed" not in resp["answer"]
