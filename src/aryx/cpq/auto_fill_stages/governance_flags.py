"""Governance precompute -- ``is_decision_attr``/``is_governed``/
``governed_source``, read by every stage from here on.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import _DECISION_REQUIRED_KEYS

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_governance_flags(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Compute the governance/decision flags the later tiers read."""
    if state.done:
        return
    # 3/4. Rule-governed default-or-first (D2/§3), else the
    # conservative single-remaining-option fallback (NO EAGER
    # EVALUATION — Issue 6's "Stop and Wait" safeguard for anything
    # not rule-governed). Decision-required attrs (country/region —
    # hwVersion removed per D1, it's a normal dependent now) always
    # ask regardless of governance.
    state.is_decision_attr = (
        any(dk in state.vn_flat for dk in _DECISION_REQUIRED_KEYS)
        # Hardware Version is MANDATORY on hardware-based catalogs
        # (APX/aSTRO25) — never blind first-by-order; must be asked
        # (or matched from NL) before Product is even eligible.
        # EXCEPT when the customer's own original wording already
        # confidently resolves to a specific device real
        # attrSequence data confirms never governs Hardware
        # Version at all (docs/Hardware_Version_APX3000_Product_
        # Anchoring_Issue.md v2.2 — e.g. "I want APX 3000", which
        # has no Hardware Version concept on the real system,
        # unlike APX NEXT). One-sided check — see
        # _hardware_version_confirmed_not_applicable's own
        # docstring for exactly when this can fire; every
        # unresolved/ambiguous case keeps today's behavior.
        or (
            engine._is_hardware_version_attr(attr)
            and not engine._hardware_version_confirmed_not_applicable(
                scope.product_anchor_hint, scope.workspace_id, scope.catalog_prefix,
                ctx.dt_cache,
            )
        )
        # productSelectionProduct_all is a shared, catalog-wide
        # option list (e.g. 325 product-line codes across every
        # product family) with no rule reliably narrowing it to the
        # resolved product — blind first-by-order picked "APX6500"
        # for an APX NEXT quote (confirmed live). Exact variable-name
        # match, not a substring, so this never widens to unrelated
        # "product*" attrs. See
        # docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md Bug 3/3c.
        # skip_always_ask overrides this ONLY when the caller
        # already confirmed the real native UI never shows it (see
        # docstring) — every other catalog keeps this unconditional.
        # ALSO deferred from pending until hardware is filled — see
        # _order_pending_hardware_before_product at end of auto_fill.
        or (
            state.vn == "productSelectionProduct_all"
            and state.vn not in (scope.skip_always_ask or ())
        )
        # "selectmodel"-named attrs can list real variants of ONE
        # product mixed with an unrelated accessory at a low menu
        # order (confirmed live: SVX's modelSelectionSelectModel_
        # viSoln has "V200 Body Worn Camera" at order=1 ahead of its
        # 3 real "SVX Video Remote Speaker Mic" variants) — blind
        # first-by-order silently picked the camera with zero
        # customer input. No rule or default_value backs this attr
        # in the ingested data (confirmed via direct Postgres query),
        # so hint-matching (checked above, unaffected by this flag)
        # is the only correct signal; without one, ask rather than
        # guess. Deliberately narrower than the full
        # _PRODUCT_IDENTIFIER_KEYS fragment set used to (see history
        # of commit 445595b) — "basemodel" and the others stay off
        # this override because they're rule-governed catalog master
        # lists, not a mix of unrelated products (APX's Base Model:
        # picking the rule-governed first option is safe there).
        # Same skip_always_ask carve-out as the productSelectionProduct_all
        # branch above -- resolve_always_ask_skips only ever populates
        # productSelectionProduct_all today, so this is currently
        # dormant, but without it any future extension of that method
        # to a "selectmodel"-named attr would have this generic
        # fragment match force it to always-ask anyway, reintroducing
        # the exact "asks a question the native UI never shows" bug
        # this carve-out pattern exists to prevent (Raven review).
        or ("selectmodel" in state.vn_flat and state.vn not in (scope.skip_always_ask or ()))
        # Confirmed live (2026-08-08): modelSelectionbaseModel_astro
        # has 16 real menu options and an empty default_value, and
        # `governed_target_ids` DOES include it (some hiding rule
        # references it as a CONDITION variable -- an earlier direct
        # per-rule-type check missed this, using the wrong attribute
        # name on HidingRule and reporting a false "0 hiding rules"),
        # but being referenced as a condition is not the same as a
        # rule ever RESOLVING it -- confirmed live it stays empty
        # regardless of governed status (§2f's own comment already
        # notes "'governed' ... really only ever meant 'some rule
        # cares about this attr,' not 'a rule decided its value'").
        # Once §2c's display_order-gated skip became active, that
        # left a genuine, structurally load-bearing customer
        # decision (16 real, meaningfully different physical base
        # models) silently unfilled -- everything downstream
        # (carrier, frequency-band pairing, provisioning) that
        # conditions on base model never gets a chance to resolve.
        #
        # A broader "any ungoverned attr with 2+ options and no
        # default" rule was tried and reverted -- it can't be
        # distinguished from a genuinely fine-to-skip optional
        # attr (confirmed by test_auto_fill_skips_unresolvable_
        # non_anchor_attr_when_layout_loaded's own "someOptional
        # Choice_astro" fixture, identically shaped, deliberately
        # expected to skip) using anything generic available here.
        # Narrowed instead to the same fragment-match convention
        # _DECISION_REQUIRED_KEYS already uses for country/region
        # -- "basemodel" is a structural naming convention (a
        # physical hardware base model selector), not a literal
        # per-catalog name, so this still generalizes across any
        # catalog using it. Unconditional on governed status, same
        # as every other decision-key fragment/anchor in this
        # expression -- none of them gate on it either.
        or "basemodel" in state.vn_flat
    )
    state.is_governed = attr.entity_id in scope.governed
    state.governed_source = "rule" if attr.entity_id in scope.rule_governed else "optional"
    state.filled_multi_now = False
