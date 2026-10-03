"""Group 2 blind pick -- real rules target this attr but none fired and
the catalog has no default_value at all.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.inferred_legal_pick import inferred_first_available
from aryx.cpq.model_scope_pick import scoped_first_available
from aryx.cpq.engine import (
    _NEVER_GUESS_SCRIPT_GOVERNED,
    _valid,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def try_rule_governed_blind(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Blind-pick the first rule-valid option, else ask."""
    if (
        attr.entity_id in scope.rule_governed
        and attr.select_type != "multi"
        and state.vn not in _NEVER_GUESS_SCRIPT_GOVERNED
        and attr.entity_id not in ctx.user_answered_dropped_ids
        and not _valid(attr.default_value)
    ):
        # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
        # PLAN_2026_08_10.md Group 2 -- real recommendation/
        # constraint/hiding rules target this attr, but none
        # fired for this exact product/region/bundle and the
        # catalog has NO default_value at all (an attr WITH a
        # default_value that simply didn't survive an active
        # constraint is a structurally different, already-
        # correct case -- stays unfilled, not force-picked --
        # see test_default_value_not_used_when_it_does_not_
        # survive_the_constraint). HITL-confirmed generic
        # policy: blind-pick the first rule-valid option rather
        # than ask forever -- same tradeoff already accepted
        # for Data-Table-sequence-governed attrs a few lines
        # above, extended here to the ordinary-rule-governed
        # case. Three existing safety nets still apply
        # unconditionally: `_NEVER_GUESS_SCRIPT_GOVERNED` (a
        # curated allowlist of attrs already confirmed broken by
        # blind-picking, see that constant's own docstring/
        # history), `user_answered_dropped_ids` (a cascade just
        # invalidated the customer's own prior answer this pass
        # -- must be RE-ASKED, never silently reguessed, same
        # guard the exactly-one-remaining-option shortcut above
        # already uses), and falling through to the unchanged
        # safety net below if there's nothing valid to pick from
        # at all (never silently drop the attr). select_type !=
        # "multi" excluded here -- this branch only ever writes
        # a scalar into `filled`; a multi-select target needs
        # `filled_multi`'s list form instead (confirmed live
        # elsewhere in this file: writing a scalar for a
        # multi-select attr silently defeats build_payload's
        # array serialization for it). Multi-select rule-
        # governed attrs in this exact shape still fall through
        # to the unchanged safety net below (ask), not covered
        # by this pass.
        #
        # Deliberately checks key PRESENCE, not the whole dict's
        # truthiness (unlike the `allowed_for_attr` computed
        # earlier in this same function, ~line 6583) --
        # apply_constraint_rules' own docstring confirms
        # constrained_opts only holds entries for attrs with an
        # ACTIVE firing constraint; an attr absent from it has no
        # active constraint at all, so every real catalog option
        # is genuinely legal to pick from -- not zero. Using
        # `.get(id, [])` here (empty-list default whenever this
        # attr merely isn't a key, e.g. some OTHER unrelated
        # attr's constraint fired this turn) would make this
        # branch pick from nothing for the exact real-world shape
        # (Wireless Carrier, Include Accidental Damage, ...) this
        # fix exists for.
        _rg_allowed = (
            set(scope.constrained_opts[attr.entity_id])
            if scope.constrained_opts and attr.entity_id in scope.constrained_opts
            else None
        )
        _rg_opts = [
            o for o in attr.options
            if _valid(o.item_value)
            and (_rg_allowed is None or o.item_value in _rg_allowed)
        ]
        if _rg_opts:
            # Same pick order as before (model-scoped, then inferred-legal,
            # then raw catalog order); split out so the picker that answered
            # is logged.
            _rg_first = scoped_first_available(
                state.vn, _rg_opts, ctx.filled, scope.workspace_id,
                scope.catalog_prefix, ctx.dt_cache,
            )
            _rg_pick_by = "model_scoped"
            if not _rg_first:
                _rg_first = inferred_first_available(
                    state.vn, _rg_opts, ctx.filled, scope.workspace_id,
                    scope.catalog_prefix, ctx.dt_cache,
                )
                _rg_pick_by = "inferred_legal"
            if not _rg_first:
                _rg_first = _rg_opts[0]
                _rg_pick_by = "raw_catalog_order"
            fill_log.log_decision(state.vn, "try_rule_governed_blind", "picked", _rg_pick_by.upper(),
                                  selected_option=_rg_pick_by,
                                  available_options=["model_scoped", "inferred_legal", "raw_catalog_order"],
                                  options_count=len(_rg_opts))
            fill_log.log_write(ctx, attr, state.vn, _rg_first.item_value, _rg_first.display_name,
                               "blind_pick_rule_governed", "blind_pick_rule_governed")
            ctx.filled[state.vn] = _rg_first.item_value
            ctx.display_filled[state.vn] = _rg_first.display_name
            ctx.sources.setdefault(state.vn, "blind_pick_rule_governed")
        else:
            ctx.pending.append(attr)
            fill_log.log_decision(state.vn, "try_rule_governed_blind", "pending", "NO_LEGAL_OPTION",
                                  allowed_is_none=_rg_allowed is None)
        return True
    return False
