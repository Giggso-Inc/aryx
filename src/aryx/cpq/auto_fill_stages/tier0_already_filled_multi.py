"""Tier 0b -- revalidate a multi-select answer already in ``ctx.filled_multi``.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq import engine as _engine_module
from aryx.cpq.auto_fill_stages.multi_fallback_unconstrained import OPTIONAL_MULTI_EMPTY_SOURCE
from aryx.cpq.model_scoping_flags import scoped_questions_enabled
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.constants import NONE_DISPLAY_PLACEHOLDER

# `_fill_signature` is looked up through the module (not imported by name
# like everything else) because tests/test_cpq_rule_loop_perf_gating_
# 2026_08_19.py monkeypatches `aryx.cpq.engine._fill_signature` directly --
# a `from ... import _fill_signature` would have captured its own frozen
# reference at import time, silently making that monkeypatch a no-op for
# code running from this module (confirmed live: this was the one real
# regression the original auto_fill_resolve move introduced).

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def _recommendation_now_satisfied(attr: "ConfigAttr", scope: "FillScope") -> bool:
    """True when a recommendation rule that targets `attr` is satisfied by what is filled now, i.e. tier 2 would give the
    attribute a value. Only an attribute some rule targets is checked at all (the call, which can evaluate BML scripts, is
    skipped for the rest). Measured on the full aSTRO25 catalog (ws 281, APX N30): one fill pass evaluates 231 script rules
    in 0.135 s and the later passes 14 in ~0 s (`log_rec_script_stats`), so there is no memo: building a fill signature per
    attribute would cost more than the check. Any failure counts as 'not satisfied' (the settled empty stays)."""
    satisfied = getattr(scope, "satisfied_recommendation", None)
    rec_by_target = getattr(scope, "rec_by_target", None)
    if satisfied is None or not rec_by_target:
        return False
    if attr.entity_id not in rec_by_target and attr.source_id not in rec_by_target:
        return False                      # no rule targets this attribute: nothing to evaluate
    try:
        return satisfied(attr, list(attr.options)) is not None
    except Exception:  # noqa: BLE001 -- a check must never break a fill
        return False


def stage_already_filled_multi(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Keep, narrow, re-display, or re-open an already-filled multi."""
    if state.done:
        return
    if state.vn in ctx.filled_multi:
        allowed_now = scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
        if allowed_now is not None:
            if ctx.sources.get(state.vn) == "default_first_available":
                # This value was picked with NOTHING to justify it
                # (no active constraint, no default_value) on some
                # earlier pass — a real constraint now exists for
                # this attr that didn't (or wasn't yet computed)
                # when the guess was made. Re-open unconditionally
                # rather than merely checking the guess is still
                # technically a member of the new allowed set —
                # "still happens to be valid" is not the same as
                # "is the answer Fix 3/4's own logic would now
                # produce", and re-deriving is idempotent (falls
                # through to the same branch below, which converges
                # to the same answer if run again with unchanged
                # inputs).
                #
                # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md
                # — same gate as the single-select branch above: only
                # actually re-derive when something relevant changed
                # since last time.
                if ctx.default_fill_signatures is not None:
                    _sig_filled = (
                        ctx.filled if not scope.signature_exclude_vns else
                        {k: v for k, v in ctx.filled.items() if k not in scope.signature_exclude_vns}
                    )
                    _sig_filled_multi = (
                        ctx.filled_multi if not scope.signature_exclude_vns else
                        {k: v for k, v in ctx.filled_multi.items() if k not in scope.signature_exclude_vns}
                    )
                    _cur_sig = _engine_module._fill_signature(
                        _sig_filled, _sig_filled_multi, {a.entity_id for a in scope.attrs},
                    )
                    if ctx.default_fill_signatures.get(state.vn) == _cur_sig:
                        ctx.display_filled[state.vn] = ", ".join(
                            next(
                                (o.display_name for o in attr.options
                                 if o.item_value == v),
                                v,
                            )
                            for v in ctx.filled_multi[state.vn]
                        )
                        fill_log.log_decision(state.vn, "stage_already_filled_multi", "kept", "FILL_SIGNATURE_UNCHANGED")
                        state.done = True
                        return
                    ctx.default_fill_signatures[state.vn] = _cur_sig
                fill_log.log_pruned(state.vn, "DEFAULT_FIRST_AVAILABLE_REDERIVE", "stage_already_filled_multi", state="reopened")
                ctx.filled_multi.pop(state.vn, None)
                ctx.sources.pop(state.vn, None)
            else:
                allowed_set = set(allowed_now)
                kept = [v for v in ctx.filled_multi[state.vn] if v in allowed_set]
                lost = [v for v in ctx.filled_multi[state.vn] if v not in allowed_set]
                if lost:
                    fill_log.log_pruned(state.vn, "MEMBERS_NOT_IN_CONSTRAINED_SET", "stage_already_filled_multi", state="narrowed")
                    ctx.dropped[state.vn] = lost
                    ctx.filled_multi[state.vn] = kept
        if not ctx.filled_multi.get(state.vn):
            if ctx.sources.get(state.vn) == "user":
                # An EMPTY selection the user explicitly confirmed
                # ("no mounts needed" declining an optional grid) is
                # a settled answer, not an unresolved attr — keep it
                # so the question is never re-asked and the payload
                # simply carries no rows. Only constraint-drops
                # (non-user sources) fall through to re-resolution.
                ctx.display_filled[state.vn] = NONE_DISPLAY_PLACEHOLDER
                fill_log.log_decision(state.vn, "stage_already_filled_multi", "kept", "USER_CHOSE_EMPTY_MULTI")
                state.done = True
                return
            if (ctx.sources.get(state.vn) == OPTIONAL_MULTI_EMPTY_SOURCE and scoped_questions_enabled()
                    and not _recommendation_now_satisfied(attr, scope)):
                # An optional multi-select left empty on purpose (scoped questions): settled, not re-resolved. Without
                # this the post-loop pass reopened it as "emptied by a constraint" and asked it among 200+ options.
                # Not when a recommendation rule has become satisfiable for it since (one that fires only after the base
                # model is derived, or after a later answer): that falls through to the reopen below, so the rule can
                # fill it.
                ctx.display_filled[state.vn] = NONE_DISPLAY_PLACEHOLDER
                fill_log.log_decision(state.vn, "stage_already_filled_multi", "kept", "OPTIONAL_MULTI_LEFT_EMPTY")
                state.done = True
                return
            fill_log.log_pruned(state.vn, "EMPTY_MULTI_REOPENED", "stage_already_filled_multi", state="reopened")
            ctx.filled_multi.pop(state.vn, None)
            ctx.sources.pop(state.vn, None)
            # Falls through to normal resolution below — the drop may
            # have emptied the selection entirely.
        else:
            ctx.display_filled[state.vn] = ", ".join(
                next((o.display_name for o in attr.options if o.item_value == v), v)
                for v in ctx.filled_multi[state.vn]
            )
            # Grid-selector re-ask (docs/CPQ_SVX_MOUNTING_TYPE_
            # ARRAY_GRID_MULTI_SELECT_PLAN_2026_08_25.md): live-
            # confirmed the customer naming just ONE of 5-6
            # narrowed mounting-type options permanently settled
            # this attr — the other real, still-valid options were
            # never offered again, even though the real native UI
            # is a grid letting several rows be filled across
            # turns. `vn in grid_selector_vns` is the SAME
            # structural signal (resolve_array_grid_links) that
            # already forces this attr onto `pending` on its FIRST
            # ask (see the is_decision_attr check below) — applying
            # it here too, gated on unpicked options actually
            # remaining and the customer not having declined
            # further picks, is not a new exception, just this
            # existing exception surviving past the first pick.
            if (
                state.vn in scope.grid_selector_vns
                and state.vn not in (scope.grid_declined_vns or ())
                and engine.grid_selector_remaining_options(
                    attr, ctx.filled_multi, scope.constrained_opts)
            ):
                ctx.pending.append(attr)
                fill_log.log_decision(state.vn, "stage_already_filled_multi", "pending", "GRID_SELECTOR_OPTIONS_REMAIN")
            state.done = True
            return
