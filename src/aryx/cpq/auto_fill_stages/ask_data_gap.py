"""Two branches of the final ask decision: skip an attr whose only
governance is a hiding rule depending on a confirmed-absent data
table, and the Data-Table-sequence-governed blind pick.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _KNOWN_MISSING_DATA_TABLES,
    _valid,
    logger,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def try_missing_data_skip(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Warn + skip a known-missing-data-table attr. True if matched."""
    if (
        attr.entity_id in scope.missing_data_target_ids
        or attr.source_id in scope.missing_data_target_ids
    ):
        # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
        # PLAN_2026_08_10.md Group 1 -- checked BEFORE
        # _dt_governed_vns below: confirmed live the real Group
        # 1 attrs (cBPQRCode_astro/fedQRCode_astro/
        # dHSAssetTagLabel_astro) ARE ALSO attrSequence-Data-
        # Table-governed, so without this ordering they'd hit
        # that branch's own blind-pick/pending decision first
        # and never reach this check at all. `attr.source_id`
        # checked too, not just `attr.entity_id` -- confirmed
        # live the real hiding rule's `target_attr_id` (e.g.
        # 18302531462 for cBPQRCode_astro) is the BM-native
        # source id, not the FalkorDB graph entity_id (292414);
        # same entity_id-vs-source_id duplicate-id convention
        # `_satisfied_recommendation` already accounts for
        # elsewhere in this file. This attr's only real
        # governance is a hiding rule that can never resolve
        # (depends on a data table confirmed absent from every
        # ingested catalog, see _KNOWN_MISSING_DATA_TABLES).
        # Asking about it forever would never converge -- warn
        # (traceable, auditable) and skip: no fill, no pending,
        # leave it genuinely unresolved until the real data gap
        # (CPQ_USER_GROUP_MAPPING_HIDING_RULE_PLAN_2026_08_10.md)
        # is actually closed.
        logger.warning(
            "cpq: %r skipped -- its only hiding rule depends on "
            "a data table confirmed absent from this catalog "
            "(%s); will never resolve until that data is "
            "ingested", state.vn, ", ".join(_KNOWN_MISSING_DATA_TABLES),
        )
        return True
    return False


def try_dt_governed_blind(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Blind-pick (or ask) an attrSequence-governed attr."""
    if state.vn in scope.dt_governed_vns and (
        scope.display_order is None or state.vn in scope.display_order
    ):
        # Deliberately checks key PRESENCE, not the whole dict's
        # truthiness (docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_
        # BLIND_PICK_PLAN_2026_08_10.md) -- confirmed live this
        # attr-absent-from-constrained_opts case is the DOMINANT
        # real shape: apply_constraint_rules only adds an entry
        # for attrs an active constraint actually fired against;
        # an attr with no active constraint firing has no entry
        # at all, meaning every real catalog option remains
        # legal, not zero. The original `.get(id, [])` pattern
        # treated "not a key" identically to "constrained to
        # nothing", silently sending real, blind-pickable attrs
        # (wirelessCarrier_astro, subscriptionBillingAddDMS
        # Coverage_astro, ...) straight to `pending` below with
        # an artificially-empty `_blind_opts` instead of ever
        # offering them a real option to pick from.
        _blind_allowed = (
            set(scope.constrained_opts[attr.entity_id])
            if scope.constrained_opts and attr.entity_id in scope.constrained_opts
            else None
        )
        _blind_opts = [
            o for o in attr.options
            if _valid(o.item_value)
            and (_blind_allowed is None or o.item_value in _blind_allowed)
        ]
        if _blind_opts:
            _blind_first = _blind_opts[0]
            ctx.filled[state.vn] = _blind_first.item_value
            ctx.display_filled[state.vn] = _blind_first.display_name
            ctx.sources.setdefault(state.vn, "blind_pick_governed")
        else:
            ctx.pending.append(attr)
        return True
    return False
