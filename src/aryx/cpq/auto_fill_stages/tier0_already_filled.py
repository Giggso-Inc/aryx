"""Tier 0a -- revalidate a single-select answer already in ``ctx.filled``.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq import engine as _engine_module
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.constants import NONE_DISPLAY_PLACEHOLDER
from aryx.cpq.derive_base_model_pick import _BLIND_SOURCE_PREFIXES

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
        #
        # Gated on `not attr.required`: honoring this on a genuinely
        # required attribute let this stage mark it "done" while
        # bom_gate_required.py's find_missing_required_fields() -- which
        # correctly still treats an empty value as missing for required
        # attrs -- would then block confirm anyway. That's not a
        # deliberate two-tier design, it's the same "leave blank" shortcut
        # applied somewhere it can't actually deliver on its promise
        # (CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T7). A required attr's
        # clear now falls through to normal re-resolution/re-ask instead,
        # so "tier0 says done" and "the gate says complete" agree again.
        if (
            not attr.required
            and ctx.filled[state.vn] == ""
            and ctx.sources.get(state.vn) == "user"
        ):
            ctx.display_filled[state.vn] = NONE_DISPLAY_PLACEHOLDER
            fill_log.log_decision(state.vn, "stage_already_filled", "kept", "USER_CHOSE_EMPTY_OPTIONAL")
            state.done = True
            return
        if (
            attr.required
            and ctx.filled[state.vn] == ""
            and ctx.sources.get(state.vn) == "user"
        ):
            # T7 follow-up (real-data testing against workspace 704,
            # 2026-09-25): the `not attr.required` gate above only blocks
            # the "(none)" shortcut -- a required attr's cleared empty
            # value still fell through to the generic `else` at the
            # bottom of this function, which unconditionally re-locks ANY
            # already-filled value as done (matched_display falls back to
            # the empty string itself when no menu option matches "").
            # Confirmed live with a real required attribute
            # (_BM_USER_CURRENCY): state.done stayed True and the attr
            # never re-entered `pending` -- the customer was never
            # re-asked, the exact "tier0 says done, the gate silently
            # blocks confirm" problem this fix's own docstring claims to
            # close. Pop and fall through to normal re-resolution instead,
            # the same pattern the stale/dropped and
            # default_first_available branches below already use for a
            # value that can't be honored as-is.
            fill_log.log_pruned(state.vn, "REQUIRED_USER_EMPTY_REOPENED", "stage_already_filled", state="reopened")
            ctx.filled.pop(state.vn, None)
            ctx.display_filled.pop(state.vn, None)
            ctx.sources.pop(state.vn, None)
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
            fill_log.log_pruned(state.vn, "NOT_IN_CONSTRAINED_SET", "stage_already_filled", state="dropped")
            ctx.dropped[state.vn] = [stale_display]
            if ctx.sources.get(state.vn) == "user":
                ctx.user_answered_dropped_ids.add(attr.entity_id)
            ctx.filled.pop(state.vn, None)
            ctx.display_filled.pop(state.vn, None)
            ctx.sources.pop(state.vn, None)
        elif str(ctx.sources.get(state.vn, "")).startswith(_BLIND_SOURCE_PREFIXES):
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
            # 2026-10-08: generalized from the literal
            # "default_first_available" check to every source tag
            # `_BLIND_SOURCE_PREFIXES` recognizes (same family
            # `derive_base_model_pick.blind_attrs()` already treats as
            # "guessed, not known") -- confirmed live, workspace 1267
            # APX 900: beltClipType_astro got blind-picked "COVERT
            # CARRY HOLSTER" (source "blind_pick_rule_governed") on an
            # early pass before Base Model was known, so
            # cpq_defaultinattr_shape_enabled's real Defaultinattr
            # default ("2.0 INCH / 5.08 CM (STANDARD)" for the
            # resolved base model) could never apply -- the literal
            # "default_first_available" check doesn't match that tag,
            # so this attribute was never reconsidered once Base Model
            # resolved on a later pass.
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
                    fill_log.log_decision(state.vn, "stage_already_filled", "kept", "FILL_SIGNATURE_UNCHANGED")
                    state.done = True
                    return
                ctx.default_fill_signatures[state.vn] = _cur_sig
            fill_log.log_pruned(state.vn, "DEFAULT_FIRST_AVAILABLE_REDERIVE", "stage_already_filled", state="reopened")
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
            fill_log.log_decision(state.vn, "stage_already_filled", "kept", "ALREADY_FILLED_STILL_VALID")
            state.done = True
            return
