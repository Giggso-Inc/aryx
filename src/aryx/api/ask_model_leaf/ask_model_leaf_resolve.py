"""Seeding the punch-in model context (`_bm_model_variable_name`) when
the catalog's own bm_catalog tree makes it unambiguous, and disambiguating
it via a real question when it doesn't, split out of `_run_cpq_turn_
inner` (Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). BM injects `_bm_model_variable_name` at
runtime; exports never carry it, which is why modelname_all (whose XML
default POINTS at it) shipped the literal token in payloads (Issue 11).
The hint fills the noise-prefixed context attr (feeds BML scripts, never
the payload), and auto_fill's pointer post-pass resolves modelname_all
from it. Logic unchanged from the original inline `if`/`elif` block; the
pending-reply resolution and the final ask-prompt building live in
sibling `ask_model_leaf_*.py` files purely to keep this file under the
line cap. `_cpq_engine` is read through the ask_api MODULE object (not
imported by name) since at least one test replaces the whole singleton
via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_model_leaf.ask_model_leaf_bind import (
    bind_turn_model_context,
    pick_top_text_match,
    seed_model_vn_from_resolution,
)
from aryx.api.ask_model_leaf.ask_model_leaf_ask_prompt import _build_model_leaf_ask_prompt
from aryx.api.ask_model_leaf.ask_model_leaf_norm import _norm_leaf
from aryx.api.ask_model_leaf.ask_model_leaf_pending_reply import _resolve_pending_model_leaf_reply
from aryx.cpq.pending_scope.pending_scope import clear_pending_scope


def _resolve_model_leaf(
    req: "Any", session: Any, reader: Any, hints: dict, catalog_prefix: str,
    switch_trigger_question: str | None,
) -> dict[str, Any] | None:
    """Ambiguous trees (APX Next: two model leaves) seed nothing. Returns
    a response dict when this turn is fully handled by the model-leaf
    disambiguation gate; None otherwise, in which case the caller
    continues with the rest of the turn (`hints` may have been mutated
    with a resolved `_bm_model_variable_name`).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    bind_turn_model_context(req, session, catalog_prefix, switch_trigger_question)
    model_vn = _cpq_engine.single_model_variable_name(
        reader, req.workspace_id, catalog_prefix)
    if not model_vn and not session.pending_model_leaf_candidates:
        # aryxent PR 2 (cpq_model_context_seed_enabled, default off): multi-
        # leaf catalogs seed the punch-in context from the resolved model --
        # only when it validates against the catalog's real leaves (same bar
        # as the resolved-leaf path below), and never while a "which model?"
        # reply is pending (that reply must still be handled).
        _seed = seed_model_vn_from_resolution()
        if _seed:
            _seed_leaf = next(
                (leaf for leaf in _cpq_engine.model_variable_candidates(
                    reader, req.workspace_id, catalog_prefix)
                 if _norm_leaf(leaf) == _norm_leaf(_seed)),
                None,
            )
            if _seed_leaf:
                hints["_bm_model_variable_name"] = _seed_leaf  # validated: force-set
                session.pending_model_leaf_candidates = []
                return None
    if model_vn:
        hints.setdefault("_bm_model_variable_name", model_vn)
        session.pending_model_leaf_candidates = []
        return None
    if session.model_leaf_resolved:
        # Live-confirmed bug (2026-08-13): this whole ambiguous-tree
        # re-resolution block had no `model_leaf_resolved` short-circuit
        # at all, unlike every other call site in this file that checks
        # it. Once already resolved on an earlier turn, `_existing_hint`
        # (from session.filled) keeps matching the same leaf every
        # subsequent turn, re-hitting `if _resolved_leaf: ... clear_
        # pending_scope(session)` unconditionally — silently wiping an
        # UNRELATED pending_scope (e.g. a live "Product — choose one"
        # disambiguation already in progress) on every turn regardless
        # of what the turn's message was actually about.
        return None
    # Amendment 10 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a catalog
    # with 2+ model leaves has no single unambiguous leaf for single_
    # model_variable_name to seed — until now this silently left _bm_
    # model_variable_name unset and no question ever asked which one was
    # meant, so the turn fell through to the unrelated "Product" attrs.
    _leaf_candidates = _cpq_engine.model_variable_candidates(
        reader, req.workspace_id, catalog_prefix)
    if not _leaf_candidates:
        return None
    # A DIFFERENT, pre-existing mechanism (extract_flag_hints) can already
    # set _bm_model_variable_name from a literal camelCase token in the
    # text — but to a value that isn't actually one of this catalog's
    # real bm_catalog leaves, since that mechanism never validates against
    # the tree at all. Validate whatever's already there first; only
    # treat it as resolved when it genuinely normalizes to one of the
    # real candidates.
    _existing_hint = hints.get("_bm_model_variable_name") or session.filled.get("_bm_model_variable_name")
    _resolved_leaf = next(
        (leaf for leaf in _leaf_candidates if _existing_hint and _norm_leaf(leaf) == _norm_leaf(_existing_hint)),
        None,
    )
    if _resolved_leaf:
        session.model_leaf_resolved = True
    elif session.pending_model_leaf_candidates:
        _resolved_leaf, _early_return = _resolve_pending_model_leaf_reply(req, session)
        if _early_return is not None:
            return _early_return
    else:
        # First time seeing this ambiguity — try to auto-resolve from
        # what the customer already said (this turn's text, plus the
        # original switch-triggering text if a switch brought us here)
        # before ever interrupting with a question.
        _combined = (
            req.question + " " + (switch_trigger_question or "")
            + " " + (session.product_anchor_question or "")
        )
        _combined_norm = _norm_leaf(_combined)
        _text_matches = [
            leaf for leaf in _leaf_candidates
            if len(_norm_leaf(leaf)) >= 5 and _norm_leaf(leaf) in _combined_norm
        ]
        if len(_text_matches) == 1:
            _resolved_leaf = _text_matches[0]
        else:
            # cpq_model_leaf_pick_top_enabled (default off): 2+ matches ->
            # take the top one instead of asking.
            _resolved_leaf = pick_top_text_match(_text_matches)

    if _resolved_leaf:
        # Force-set, not setdefault: extract_flag_hints may have already
        # put an unvalidated value here — this is the validated,
        # canonical leaf identifier and must win.
        hints["_bm_model_variable_name"] = _resolved_leaf
        session.pending_model_leaf_candidates = []
        session.model_leaf_resolved = True
        clear_pending_scope(session)
        return None
    return _build_model_leaf_ask_prompt(req, session, _leaf_candidates)
