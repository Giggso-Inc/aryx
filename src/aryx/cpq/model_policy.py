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

T6 Phase 3: `_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS` switched from shadow
to real via `resolve_optional_empty_fill_membership()`. A third named
constant, `_RECOMMENDED_CONFIG_ONLY_VNS` (a `CpqEngine` CLASS
attribute, unlike the first two module-level ones), was then added
directly at the real/scoped stage -- no separate shadow slice, since
its one real consumer (`mandatory_tier_c_vns`) already unconditionally
resolves CPQ model candidates via the pre-existing, separately-cached
`_cpq_model_candidates` (not the attrToVarMapping-backed path that
motivated the shadow-first discipline for the other two), so there
was no new RDB-touching call to de-risk first.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates
from aryx.cpq.opt_out_and_duplicates import _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS

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

_LEGACY_RECOMMENDED_CONFIG_ONLY_VNS: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "systemEnhancementFeatureType_astro",
        "serviceTypeAdditionalDMSCoverage_astro",
        "dmsDuration_astro", "dMSDurationYears_astro",
        "antennasType_astro",
        "beltClipType_astro",
        "advancedSystemKeyHardwareKey_astro",
        "deviceManagementTraining_astro",
        "trainTheTrainerTraining_astro",
        "packingPackageType_astro",
        "documentationTestResultsRatedAudioPrintoutLabel_astro",
    }),
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


def recommended_config_only_vns(cpq_model: str) -> frozenset[str]:
    """The set of variable_names individually verified Recommended-
    Configuration-only for `cpq_model` (excluded from `mandatory_tier_c_
    vns`'s Tier C set) -- legacy policy-table lookup only for now (see
    module docstring); returns `frozenset()` for any model with no
    policy entry, never a guess."""
    return _LEGACY_RECOMMENDED_CONFIG_ONLY_VNS.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


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


def resolve_optional_empty_fill_membership(
    vn: str, product_name: str, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> bool:
    """Whether `vn` should be treated as genuinely optional-empty for the
    session's actual CPQ model(s) -- resolves via the real, per-model
    `optional_empty_fill_accepted_vns` policy table, falling back to the
    legacy `_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS` membership check when
    `workspace_id`/`product_name` aren't available yet, when no model
    candidates resolve, or when candidate resolution itself fails. Never
    raises. A resolved candidate with no policy entry is real information
    (that model is confirmed NOT verified for this attr), not a guess --
    only the "couldn't resolve at all" cases fall back to the literal.

    Gated behind `model_policy_scoped_resolution_enabled` (default off),
    checked FIRST, before anything else: `_cpq_model_candidates` touches
    the same RDB-backed data source that already caused one hung test
    this session (CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3) --
    same safety rationale as `catalog_profile.resolve_base_model_vn`.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return vn in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    if workspace_id is None or not product_name:
        return vn in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "ModelPolicy resolution failed for vn=%r (ws=%s) -- falling "
            "back to the legacy constant", vn, workspace_id,
        )
        return vn in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    if not models:
        return vn in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    return any(vn in optional_empty_fill_accepted_vns(m) for m in models)


def resolve_recommended_config_only_membership(
    vn: str, legacy_members: frozenset[str], cpq_models: "tuple[str, ...] | None",
) -> bool:
    """Whether `vn` should be excluded as a Recommended-Configuration-
    only attr for the session's actual CPQ model(s) -- resolves via the
    real, per-model `recommended_config_only_vns` policy table, falling
    back to `legacy_members` when no model candidates are available.

    Unlike `resolve_optional_empty_fill_membership`, this does NOT
    resolve its own model candidates: its one real caller
    (`mandatory_tier_c_vns`) already computes them unconditionally via
    the pre-existing, separately-cached `_cpq_model_candidates` call
    (not gated -- this has always been the case, long before this
    audit's work, and that function has its own 300s-TTL cache) --
    recomputing them here would be a redundant RDB-adjacent call within
    the same turn for no benefit. `legacy_members` is passed by the
    caller rather than imported as a fixed constant because `engine.
    _RECOMMENDED_CONFIG_ONLY_VNS` is a `CpqEngine` CLASS attribute read
    off the instance (`mandatory_tiers.py`'s own docstring: "preserving
    the original self. lookup -- subclass/instance overrides still
    win") -- importing a frozen module-level constant here would
    silently break that override contract.

    Gated behind `model_policy_scoped_resolution_enabled` (same flag as
    `resolve_optional_empty_fill_membership`, for the same off-by-
    default rollout discipline) -- when off, or when no candidates were
    resolved, behaves byte-identically to today's `vn in engine.
    _RECOMMENDED_CONFIG_ONLY_VNS` check.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return vn in legacy_members
    if not cpq_models:
        return vn in legacy_members
    return any(vn in recommended_config_only_vns(m) for m in cpq_models)
