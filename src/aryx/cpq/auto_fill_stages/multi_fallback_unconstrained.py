"""Genuinely-unconstrained multi-select blind pick, respecting any real
ingested Data Table whitelist for this exact context.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.model_policy import resolve_select_all_narrowed_legal_multi_membership

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def blind_pick_narrowed(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
    candidate_opts: list,
) -> None:
    """Blind-pick (or select-all) from the real narrowed legal set."""
    # Tagged with a DISTINCT source (not "default") so the
    # re-validation step above (`if vn in filled_multi:`)
    # can tell "guessed with nothing to justify it" apart
    # from a genuine default_value match. Necessary because
    # evaluate_rules_loop's fixed-point iteration can call
    # auto_fill on an EARLY pass where this attr is
    # genuinely unconstrained (e.g. before
    # productSelectionProduct_all itself is filled), lock
    # this guess into filled_multi, and then a LATER pass
    # activates a real constraint on the same attr — the
    # re-validation step would otherwise just confirm the
    # guessed value is still technically a member of the
    # new allowed set and keep it unquestioned, never
    # re-deriving the correct Fix-3 default-or-empty
    # answer for the now-real constraint (confirmed live:
    # additionalSystemEnhancementFeatureType_astro got
    # guessed "DISABLE CLOUD SERVICES" before Product was
    # resolved, then kept it across every later pass even
    # after its real 9-of-11 constraint activated).
    # docs/CPQ_MULTISELECT_BLIND_PICK_RESPECTS_WHITELIST_
    # PLAN_2026_08_10.md -- confirmed live (carrierSelection
    # MultiSelect_astro): the raw catalog menu order can
    # include real, data-proven-ILLEGAL options for the
    # current context (e.g. a carrier only legal for a
    # different destination country). When the real
    # ingested Data Table has ANY coverage for this attr
    # here -- even narrowed to 2+ values, not just the
    # single-confident-match case _resolve_via_data_tables
    # already handles above -- pick from that real,
    # narrowed set instead of the unfiltered raw menu.
    # `None` (no table coverage at all) falls back to
    # today's original raw-order pick, unchanged.
    _dt_legal = (
        engine._resolve_narrowed_legal_values(
            state.vn, ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        )
        if scope.workspace_id is not None else None
    )
    _narrowed_opts = (
        [o for o in candidate_opts if o.item_value in _dt_legal]
        if _dt_legal is not None else candidate_opts
    )
    if _narrowed_opts:
        if resolve_select_all_narrowed_legal_multi_membership(
            state.vn, ctx.filled.get("productSelectionProduct_all", ""),
            scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        ):
            # Live-confirmed (2026-08-16): native CPQ UI
            # checks EVERY Whitelist-confirmed-legal option
            # by default for these specific attrs (real-
            # world meaning is "which of these does this
            # unit support", e.g. Frequency Band coverage)
            # -- picking only _narrowed_opts[0] silently
            # dropped 2 of 3 real, legal, native-UI-checked
            # values (modelSelectionFrequencyBandMsl_astro:
            # only '700/800 MHZ' ever reached the payload,
            # never 'VHF'/'UHF'). Deliberately a narrow,
            # named allowlist, NOT a blanket change to this
            # branch -- carrierSelectionMultiSelect_astro
            # hits this exact same code path and genuinely
            # needs the OPPOSITE behavior (native UI leaves
            # it unresolved/"Invalid selection" rather than
            # auto-checking every legal carrier), so
            # defaulting to "select all" here for every
            # attr would be a regression, not a fix.
            ctx.filled_multi[state.vn] = [o.item_value for o in _narrowed_opts]
            ctx.display_filled[state.vn] = ", ".join(
                o.display_name for o in _narrowed_opts)
            ctx.sources.setdefault(state.vn, "default_first_available")
        else:
            first_opt = _narrowed_opts[0]
            ctx.filled_multi[state.vn] = [first_opt.item_value]
            ctx.display_filled[state.vn] = first_opt.display_name
            ctx.sources.setdefault(state.vn, "default_first_available")
    else:
        # Real Data Table confirms ZERO legal values for
        # this exact context (`_dt_legal == []`) -- a
        # genuine, data-proven answer, not something to
        # guess past. Same empty outcome as the sibling
        # `else` below, reached here instead since
        # `is_unconstrained and candidate_opts` already
        # matched on the raw (pre-whitelist) option list.
        ctx.filled_multi[state.vn] = []
        ctx.display_filled[state.vn] = "(none)"
        ctx.sources.setdefault(state.vn, "default")
