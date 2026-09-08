"""Invalidating cascade dependents for a STEP-6 cascade change, split out
of `_handle_cascade` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_
cascade_apply_value.py`/`ask_handle_cascade.py` under the line cap.
Logic unchanged from the original inline block. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_invalidate_stale_base_model import _invalidate_stale_base_model
from aryx.cpq.session_guard import clear_clarify, push_snapshot


def _invalidate_cascade_dependents(
    req: "Any", session: Any, attrs: list, changed_attr: Any,
    hiding_rules: list, rec_rules: list, con_rules: list,
) -> tuple:
    """Snapshots for undo, clears clarify state, computes hints, finds and
    strips cascade dependents from session state (including the stale
    Base Model check), and computes the constrained-option scope for
    `changed_attr` reused by the answer-match attempt, the rejected-
    option exclusion, and the retry prompt. Returns (hints, negated_vns,
    catalog_prefix, dependent_labels, hc_allowed).
    """
    _cpq_engine = _ask_api_module._cpq_engine
    push_snapshot(session, reason="cascade")
    clear_clarify(session, getattr(changed_attr, "variable_name", None))
    by_eid = {a.entity_id: a for a in attrs}
    hints = _cpq_engine.extract_hints(req.question)
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    # Accumulate across turns (not just this one) — see CpqSession.negated_vns.
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    # Find dependent attrs to invalidate
    dependent_eids = _cpq_engine.find_cascade_dependents(
        changed_attr, attrs, hiding_rules, rec_rules, con_rules,
    )
    # set_type=="2" attrs are transient UI/action-layer fields, always
    # excluded from the final payload (build_payload's own unconditional
    # rule) — they never re-enter `filled`/`pending_variables` after this
    # rerun either, so naming them here as "needing fresh values" is
    # misleading (live-verified: "Include a Spare Battery with each body
    # camera" was announced as recalculating, then silently never
    # reappeared anywhere — correct outcome, confusing wording).
    dependent_labels = [
        _cpq_engine.disambiguated_label(by_eid[eid], attrs) for eid in dependent_eids
        if eid in by_eid and by_eid[eid].set_type != "2"
    ]

    # Strip changed attr + all dependents from filled. A dependent can be
    # select_type=="multi" (its real value lives in session.filled_multi,
    # never session.filled) -- confirmed live 2026-08-20: switching
    # Hardware Version from 5G to 4G-only correctly cleared the scalar
    # side but left a multi-select dependent's stale value (e.g.
    # carrierSelectionMultiSelect_astro) sitting in filled_multi for the
    # rest of the session, which could keep a hiding rule keyed off "does
    # this attr have a value" permanently wrong -- not a one-turn delay,
    # since nothing ever re-clears it. Popping unconditionally from both
    # is safe: a scalar attr is never a key in filled_multi and vice versa.
    # changed_attr's own filled_multi entry (if it's the multi-select
    # itself being directly changed) is deliberately left alone here --
    # the multi-select branch below reads and UNIONs into it on purpose
    # ("include X" adds a row, never wipes prior selections). Only
    # DEPENDENTS get the filled_multi pop.
    session.filled.pop(changed_attr.variable_name, None)
    session.display_filled.pop(changed_attr.variable_name, None)
    session.filled_source.pop(changed_attr.variable_name, None)
    for eid in dependent_eids:
        a = by_eid.get(eid)
        if a:
            session.filled.pop(a.variable_name, None)
            session.filled_multi.pop(a.variable_name, None)
            session.display_filled.pop(a.variable_name, None)
            session.filled_source.pop(a.variable_name, None)
    _invalidate_stale_base_model(session, changed_attr, dependent_eids, by_eid)

    # Constraint scope for changed_attr — computed ONCE and reused for the
    # answer-match attempt, the rejected-option exclusion, and the retry
    # prompt (docs/CPQ_SESSION_2026_07_29_ISSUES_PLAN.md #3/#10): previously
    # this block called apply_answer/apply_multi_answer/next_question_prompt
    # with NO constrained_item_values at all, so a mismatch's retry prompt
    # fell back to the attr's full unconstrained option list (e.g. Product's
    # entire ~328-model catalog instead of the active APX NEXT family) and
    # a value shown as a valid option moments earlier could then fail to
    # re-match. bml_eval=None here is the same opt-out convention used
    # elsewhere in this file (script-backed constraint rules are skipped,
    # never guessed — declarative condition_attr_id/value rules still
    # apply), so this only narrows scope when it can do so with certainty.
    _hc_constrained = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval=None, filled_multi=session.filled_multi,
    )
    hc_allowed = _hc_constrained.get(changed_attr.entity_id)
    return hints, negated_vns, catalog_prefix, dependent_labels, hc_allowed
