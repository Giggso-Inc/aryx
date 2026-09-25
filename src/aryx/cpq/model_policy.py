"""ModelPolicy -- per-catalog+CPQModel behavior policy.

Phase 3 (T6) pilot slice of CPQ_Hardcode_Audit_dev_oci_2026-09-25.md:
proves the "legacy" arm of the proposed ModelPolicy design (a static
policy table per CPQModel, reproducing today's hand-verified,
per-attribute behavior exactly) for two of T6's ten named constants --
`_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS` and `_DUPLICATE_DISPLAY_NAME_
CANONICAL_ITEM_VALUE` (both in `opt_out_and_duplicates.py`).

Picked over the other 8 named constants for this first slice because
both are simple, static, individually-verified-per-attribute values
with no live-data dependency and no entanglement with other logic --
confirmed via their real consumers (`turn_intent/apply.py`, `auto_fill_
stages/multi_optout_and_empty.py`), each a single `.get()`/`in` check.
Two other originally-considered candidates were ruled out on closer
inspection: `mandatory_tier_c_vns`/`_ATTRSEQ_CONFIRMED_REQUIRED_VNS`
sit inside `mandatory_input.py`'s densely-gated, three-consumer Tier
A/B/C logic (real restructuring risk, not a safe first slice), and
`_KNOWN_MISSING_DATA_TABLES` (UserGroupMapping) is deliberately
per-WORKSPACE-verified, not per-catalog-static (PR #211 review) -- a
static policy-file entry for it would silently reintroduce the exact
bug that review fixed.

Standalone and NOT wired into any real call site yet -- this slice
only proves the loader mechanism itself returns byte-identical values
to today's hardcoded constants for APX NEXT; `opt_out_and_duplicates.py`
itself is untouched.

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 follow-up: `shadow_check_
optional_empty_fill_vns()` below is this module's first real-call-site
touch -- a shadow-only comparison wired into `try_multi_optional_empty`
(gated off by default), the "shadow" phase of T6's proposed legacy-→
shadow-→scoped-→remove rollout. `duplicate_display_name_canonical_
item_value`'s only real consumer, `apply_answer()`, has no `cpq_model`
parameter and 15 call sites across 11 files -- widening its signature
is real restructuring risk, not a safe next step, so that constant
stays standalone for now.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates

logger = logging.getLogger(__name__)

# "Legacy" policy table: today's exact, individually-verified behavior
# per CPQModel, reproducing opt_out_and_duplicates.py's two hand-
# verified constants without changing them. Additive -- an
# unrecognized model returns the empty/no-op default, never a guess.
_LEGACY_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "promoApplicationServices_astro",
        "additionalApplicationServices_astro",
        "aTAKNonPromoApplicationServices_astro",
    }),
}

_LEGACY_DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE: dict[str, dict[str, str]] = {
    "APXNEXT": {
        "applicationServicesIntroBundle_astro": "5 YEARS",
    },
}


def optional_empty_fill_accepted_vns(cpq_model: str) -> frozenset[str]:
    """The set of variable_names individually verified genuinely
    optional-empty for `cpq_model` -- legacy policy-table lookup only
    for now (see module docstring); returns `frozenset()` for any
    model with no policy entry, never a guess."""
    return _LEGACY_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


def duplicate_display_name_canonical_item_value(cpq_model: str) -> dict[str, str]:
    """`{variable_name: canonical item_value}` for attrs with
    catalog-authored duplicate-display-name options, for `cpq_model`
    -- legacy policy-table lookup only for now (see module docstring);
    returns `{}` for any model with no policy entry, never a guess."""
    return dict(_LEGACY_DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE.get(
        (cpq_model or "").strip().upper(), {},
    ))


def shadow_check_optional_empty_fill_vns(
    vn: str, legacy_membership: bool, product_name: str, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> None:
    """Best-effort, log-only: for each CPQ model `product_name` resolves
    to, compare `legacy_membership` (today's `_OPTIONAL_EMPTY_FILL_
    ACCEPTED_VNS` membership check, computed by the caller) against
    whether `vn` is in `optional_empty_fill_accepted_vns(model)`.
    Never raises, never returns anything -- purely observational, same
    contract as `catalog_profile.shadow_check_role_vn`."""
    if workspace_id is None:
        return
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
        for model in models:
            policy_membership = vn in optional_empty_fill_accepted_vns(model)
            if policy_membership != legacy_membership:
                logger.warning(
                    "ModelPolicy shadow mismatch: vn=%r model=%r "
                    "legacy_membership=%r policy_membership=%r (ws=%s "
                    "catalog_prefix=%r)",
                    vn, model, legacy_membership, policy_membership,
                    workspace_id, catalog_prefix,
                )
    except Exception:
        logger.exception(
            "ModelPolicy shadow check failed for vn=%r (ws=%s) -- "
            "ignored, legacy path unaffected", vn, workspace_id,
        )
