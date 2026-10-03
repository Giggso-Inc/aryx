"""Tier 3 -- the catalog's own XML ``default_value``.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import _valid

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_default_value(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Resolve from default_value (incl. the boolean-default branch)."""
    if state.done:
        return
    # 3. Default value (pointer-defaults excluded — see
    # _is_pointer_default above; the post-pass resolves them).
    # Also skipped when an active constraint has already narrowed
    # this attr's allowed set and the raw default isn't in it
    # (docs/config_consistency_issues_2026-07-30.md Issue 7
    # follow-up: the catalog's own generic default_value is not
    # guaranteed to satisfy a PRODUCT-SPECIFIC constraint rule —
    # confirmed live, Carry Type's catalog default "2.0 INCH /
    # 5.08 CM (STANDARD)" is genuinely invalid for APX NEXT Single
    # Band's own constraint rule, yet this step locked it in
    # unconditionally before the constraint-aware fallback a few
    # lines below (which already correctly picks a real, valid
    # option) ever got a chance to run — forcing a BOM-gate
    # correction round-trip on every single default order for
    # this product). Falling through here instead of locking in a
    # known-bad value lets that existing fallback do its job.
    _default_excluded_by_constraint = (
        scope.constrained_opts is not None
        and attr.entity_id in scope.constrained_opts
        and attr.default_value not in scope.constrained_opts[attr.entity_id]
    )
    if (
        not state.value and _valid(attr.default_value)
        and not scope.is_pointer_default(attr)
        and not _default_excluded_by_constraint
        # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): once a
        # layout map is loaded, a bare catalog default_value no
        # longer fills the attribute on its own — falls through to
        # the final ask-branch, which §2c then skips (not asks)
        # since this isn't a decision-anchor or grid selector.
        and scope.display_order is None
    ):
        state.value = attr.default_value
        state.source = "default"
        fill_log.log_decision(state.vn, "stage_default_value", "picked", "XML_DEFAULT_VALUE")
        state.display = next(
            (o.display_name for o in attr.options
             if o.item_value == attr.default_value),
            attr.default_value,
        )
        # Issue 5 root cause 3 (docs/config_consistency_issues_
        # 2026-07-30.md): some menu attrs carry a legacy boolean-era
        # option pair (item_value "YES"/"NO") alongside a
        # differently-spelled current/canonical option that shares
        # the SAME display_name (confirmed live: baselineReleaseSW_
        # astro has both "YES"->"Baseline Release" and "BASELINE
        # RELEASE"->"Baseline Release"). If the catalog's
        # default_value happens to be the bare legacy "YES"/"NO"
        # spelling, prefer a same-display-name sibling option whose
        # item_value ISN'T a bare boolean literal — it's the same
        # real-world choice, just the non-deprecated spelling.
        # Generic (no attribute names hardcoded): only fires when
        # such a sibling genuinely exists, never invents a value.
        if state.value.strip().upper() in ("YES", "NO"):
            _canonical_sibling = next(
                (o for o in attr.options
                 if o.display_name == state.display
                 and o.item_value.strip().upper() not in ("YES", "NO")),
                None,
            )
            if _canonical_sibling is not None:
                state.value = _canonical_sibling.item_value
                state.display = _canonical_sibling.display_name
    elif (not state.value and attr.select_type == "boolean"
            and attr.default_value.strip().lower() in ("true", "false")
            # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): a
            # second, separate default_value branch I missed on the
            # first pass — same bare-catalog-default shape as the
            # sibling branch above, gated the same way. Found live:
            # a boolean attr's "true"/"false" default_value slipped
            # through with a "default"-tagged value even after §2d
            # shipped, because this branch has its own independent
            # default_value check instead of sharing the one above.
            and scope.display_order is None):
        # _valid() treats the literal string "false" as a none-sentinel
        # (_NONE_VALUES) — correct for single-select dropdowns where
        # "FALSE" can mean "no selection", but wrong for a genuinely
        # boolean-typed attr, where "false" IS the real, meaningful
        # value. Without this, a boolean's own valid default gets
        # silently discarded here, falls through ungoverned, and
        # (confirmed live) can reach the decision-required cascade
        # below and get contaminated with an unrelated sibling's raw
        # string value (e.g. isUltimateDestinationCountryCA_astro
        # picking up "United States" from CRM_BILL_COUNTRY).
        state.value = attr.default_value.strip().lower()
        state.source = "default"
        state.display = "Yes" if state.value == "true" else "No"
        fill_log.log_decision(state.vn, "stage_default_value", "picked", "BOOLEAN_DEFAULT")
