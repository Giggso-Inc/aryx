"""Tier 0a -- revalidate a single-select answer already in ``ctx.filled``.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq import engine as _engine_module
from aryx.cpq.auto_fill_stages.state import AttrResolution

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


def stage_already_filled(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Keep, re-display, or re-open an already-filled single-select."""
    if state.done:
        return
    if state.vn in ctx.filled:
        # Deliberately cleared by the user (D4,
        # docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md) — an empty
        # value tagged filled_source="user" is a standing "leave
        # this blank" decision, the single-select counterpart of
        # filled_multi's existing empty-plus-"user" "(none)"
        # convention below. Never re-guessed by the blind
        # first-by-order fallback on a later pass; only a genuine
        # rule re-assertion (apply_recommendation_rules' truthy
        # check, not `in filled`) overrides it, exactly like it
        # would override any other stale value.
        if ctx.filled[state.vn] == "" and ctx.sources.get(state.vn) == "user":
            ctx.display_filled[state.vn] = "(none)"
            state.done = True
            return
        # Already answered in a prior turn — but a cascade may have
        # narrowed this attr's allowed set since then (single-select
        # counterpart of the multi-select re-validation below, §5/
        # Phase J). If the locked value is no longer allowed, clear
        # it and fall through to re-resolution instead of keeping a
        # stale, now-invalid answer.
        allowed_single = (
            scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
        )
        if allowed_single is not None and ctx.filled[state.vn] not in allowed_single:
            stale_display = ctx.display_filled.get(state.vn, ctx.filled[state.vn])
            ctx.dropped[state.vn] = [stale_display]
            if ctx.sources.get(state.vn) == "user":
                ctx.user_answered_dropped_ids.add(attr.entity_id)
            ctx.filled.pop(state.vn, None)
            ctx.display_filled.pop(state.vn, None)
            ctx.sources.pop(state.vn, None)
        elif ctx.sources.get(state.vn) == "default_first_available":
            # Live bug (2026-08-09): this value was picked with
            # NOTHING to justify it (§2f's blind first-by-order
            # fallback, when neither a satisfied recommendation nor
            # the real Data Table constraint resolved a value on
            # THAT pass) -- but evaluate_rules_loop's `filled` state
            # keeps growing richer pass over pass, and the Data
            # Table lookup that failed to narrow to one value on an
            # EARLY pass (not enough context yet) can very much
            # succeed on a LATER one. Confirmed live:
            # extendRangeTo762764MHz_astro got blind-picked "YES"
            # on an early pass; the real ingested constraint data,
            # given the FULL final filled state, unambiguously says
            # "NO" -- but nothing ever re-checked it once filled,
            # same "single-select re-validation" gap the
            # multi-select branch below already closes for its own
            # "default_first_available" tag. Re-open it every pass
            # instead of locking in a guess forever -- worst case
            # (still no real resolution) it just gets re-guessed
            # identically; best case, a real answer now overrides
            # the earlier guess before the customer ever sees the
            # wrong one.
            #
            # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md:
            # "every pass" was multiplying evaluate_rules_loop's cost
            # up to 8x per turn -- gate the re-derivation on whether
            # anything relevant has actually changed since it was
            # last (re)derived. Skipped entirely when the caller
            # doesn't opt in (`_default_fill_signatures is None`),
            # identical to every pre-existing call site.
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
                    matched_display = next(
                        (o.display_name for o in attr.options
                         if o.item_value == ctx.filled[state.vn]),
                        ctx.filled[state.vn],
                    )
                    ctx.display_filled[state.vn] = matched_display
                    state.done = True
                    return
                ctx.default_fill_signatures[state.vn] = _cur_sig
            ctx.filled.pop(state.vn, None)
            ctx.display_filled.pop(state.vn, None)
            ctx.sources.pop(state.vn, None)
        else:
            matched_display = next(
                (o.display_name for o in attr.options
                 if o.item_value == ctx.filled[state.vn]),
                ctx.filled[state.vn],
            )
            ctx.display_filled[state.vn] = matched_display
            state.done = True
            return
