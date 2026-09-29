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

A fourth, `_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS` (`fill_signature.py`
-- a plain module-level constant with exactly one member and one real
consumer, `auto_fill_stages/multi_fallback_unconstrained.py`), was
added the same way as the first: resolves its own model candidates
via `product_name`, mirroring `resolve_optional_empty_fill_membership`
exactly.

A fifth, `_CONFIRMED_DEAD_ATTRS` (`data_table_bridge/attr_governance.
py` -- a plain module-level constant, one real consumer,
`_suppress_ungoverned_attrs`, the SAME function T1's Base Model
switch-over already touched), was added the same way as the third:
reuses that function's already-resolved candidates tuple rather than
re-deriving them, since `_cpq_model_candidates` is unconditional and
separately-cached there already.

A sixth, `_BLIND_FILL_RISK_ACCEPTED_VNS` (`blind_fill_constants.py` --
a plain module-level constant, three real consumers across `auto_fill_
stages/multi_fallback.py`, `auto_fill_stages/tier6_single_b.py`
(3 checks), and `auto_fill_stages/multi_optout_and_empty.py`), was
added the same way as the first and fourth: resolves its own model
candidates via `product_name`, since every consumer already has
`ctx`/`scope` (hence `ctx.filled`, `ctx.dt_cache`, `scope.workspace_id`,
`scope.catalog_prefix`) in local scope but none has a pre-resolved
candidates tuple to reuse.

A seventh, `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES` (`hiding_rules/
type11.py` -- membership over hiding-rule NAME strings, not variable
names, otherwise the same shape as the sixth), was added after
threading a new `product_name` parameter down 3 signatures (`engine.
load_hiding_rules` -> `hiding_rules.load_hiding_rules` -> `_load_type11_
hiding_rules`) -- every one of its 7 real call sites already has a
resolved product name locally in scope, so no call-site logic changed,
only a new argument passed one level deeper. Confirmed live (direct
`python3 -c` import reproduction, both directions) that `model_policy.
py` importing `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES` from `type11.
py` at module scope is safe -- `type11.py` is imported by `engine.py`
at line 496, long after `engine.py`'s own `logger`/`_valid` are defined,
unlike `attr_governance.py`'s early-chain case. The REVERSE import
(`type11.py` importing the resolver back from `model_policy.py`) would
be a genuine two-module cycle, though -- so, mirroring the
`_CONFIRMED_DEAD_ATTRS` fix, `type11.py` imports the resolver function
itself LAZILY, inside `_load_type11_hiding_rules`'s function body, not
at module scope.

An eighth, `_KNOWN_SIBLING_PAIRS` (`engine.py` -- a `CpqEngine` CLASS
attribute, a tuple of variable_name PAIRS rather than a per-vn
membership set), was added with a new resolver shape: `resolve_known_
sibling_pairs` both self-resolves its own model candidates (Shape A --
its one real consumer, `exclusive_sibling_family_exclusions`, has no
pre-resolved candidates tuple in scope) AND takes `legacy_members` as a
parameter, not an import (Shape-B's override-preservation reasoning,
since `_KNOWN_SIBLING_PAIRS` is a class attribute read off the
instance). Returns the UNION of every resolved candidate model's
disclosed pairs, de-duplicated, order-preserving -- the natural
generalization of the vn-membership resolvers' `any(...)` check from a
boolean to a collection. `product_name`/`workspace_id`/`catalog_prefix`
are threaded down 4 signatures from the one real call site (`_step10_
enforce_siblings_and_multi_hint`, which already has all three locally)
through `enforce_exclusive_sibling_families` (both the free function
and its `CpqEngine` wrapper) to `exclusive_sibling_family_exclusions`
(both the free function and its `CpqEngine` wrapper) -- no circular
import risk, since `model_policy.py` imports nothing from `sibling_
exclusions.py` (the legacy value is passed by the caller, not
imported), so this is a plain one-directional import, no lazy-import
workaround needed.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.blind_fill_constants import _BLIND_FILL_RISK_ACCEPTED_VNS
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates
from aryx.cpq.fill_signature import _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
from aryx.cpq.hiding_rules.type11 import _DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES
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

_LEGACY_CONFIRMED_DEAD_ATTRS: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "modelSelectionFrequencyBands_astro",
        "modelSelectionFrequencyBandPlus_astro",
    }),
}

_LEGACY_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "modelSelectionFrequencyBandMsl_astro",
    }),
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

_LEGACY_BLIND_FILL_RISK_ACCEPTED_VNS: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "accessoriesSolutionSet_astro",
        "relatedServicesType_astro",
        "relatedServiceCategory_astro",
        "selectEndUserType_astro",
        "baselineReleaseSW_astro",
        "applicationServicesSelection_astro",
        "carrierSelectionMultiSelect_astro",
        "packingPackageType_astro",
    }),
}

_LEGACY_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES: dict[str, frozenset[str]] = {
    "APXNEXT": frozenset({
        "Hide Optional Peripherals 900 MHz Hybrid Combiner For G Series If No Value Available",
    }),
}

_LEGACY_KNOWN_SIBLING_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "APXNEXT": (
        ("wirelessCarrier_astro", "carrierSelectionMultiSelect_astro"),
    ),
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


def confirmed_dead_attrs(cpq_model: str) -> frozenset[str]:
    """The set of variable_names individually confirmed orphaned/legacy
    (zero attrSequence rows anywhere, but native CPQ never renders them)
    for `cpq_model` -- legacy policy-table lookup only for now (see
    module docstring); returns `frozenset()` for any model with no
    policy entry, never a guess."""
    return _LEGACY_CONFIRMED_DEAD_ATTRS.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


def select_all_narrowed_legal_multi_vns(cpq_model: str) -> frozenset[str]:
    """The set of variable_names individually verified to select EVERY
    Whitelist/Data-Table-confirmed-legal option by default (coverage
    semantics, not pick-one) for `cpq_model` -- legacy policy-table
    lookup only for now (see module docstring); returns `frozenset()`
    for any model with no policy entry, never a guess."""
    return _LEGACY_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


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


def blind_fill_risk_accepted_vns(cpq_model: str) -> frozenset[str]:
    """The set of variable_names individually verified safe to blind-fill
    despite `_no_real_fill_justification` finding no rule coverage, for
    `cpq_model` -- legacy policy-table lookup only for now (see module
    docstring); returns `frozenset()` for any model with no policy
    entry, never a guess."""
    return _LEGACY_BLIND_FILL_RISK_ACCEPTED_VNS.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


def dt_whitelist_substitute_hiding_rule_names(cpq_model: str) -> frozenset[str]:
    """The set of hiding-rule NAME strings individually confirmed safe to
    substitute a real Data-Table whitelist check for a missing BmFunction
    script, for `cpq_model` -- legacy policy-table lookup only for now
    (see module docstring); returns `frozenset()` for any model with no
    policy entry, never a guess."""
    return _LEGACY_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES.get(
        (cpq_model or "").strip().upper(), frozenset(),
    )


def known_sibling_pairs(cpq_model: str) -> tuple[tuple[str, str], ...]:
    """The disclosed sibling-pair exceptions (see `CpqEngine._KNOWN_
    SIBLING_PAIRS`'s own docstring) for `cpq_model` -- legacy
    policy-table lookup only for now (see module docstring); returns
    `()` for any model with no policy entry, never a guess."""
    return _LEGACY_KNOWN_SIBLING_PAIRS.get(
        (cpq_model or "").strip().upper(), (),
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


def resolve_select_all_narrowed_legal_multi_membership(
    vn: str, product_name: str, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> bool:
    """Whether `vn` should select EVERY Whitelist/Data-Table-confirmed-
    legal option by default (coverage semantics) rather than blind-
    picking one, for the session's actual CPQ model(s) -- resolves via
    the real, per-model `select_all_narrowed_legal_multi_vns` policy
    table, falling back to the legacy `_SELECT_ALL_NARROWED_LEGAL_
    MULTI_VNS` membership check when `workspace_id`/`product_name`
    aren't available yet, when no model candidates resolve, or when
    candidate resolution itself fails. Never raises. Same contract,
    same gate, same fallback shape as `resolve_optional_empty_fill_
    membership` -- see its docstring for the full safety rationale.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return vn in _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    if workspace_id is None or not product_name:
        return vn in _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "ModelPolicy resolution failed for vn=%r (ws=%s) -- falling "
            "back to the legacy constant", vn, workspace_id,
        )
        return vn in _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    if not models:
        return vn in _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS
    return any(vn in select_all_narrowed_legal_multi_vns(m) for m in models)


def resolve_blind_fill_risk_accepted_membership(
    vn: str, product_name: str, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> bool:
    """Whether `vn` is individually verified safe to blind-fill despite
    `_no_real_fill_justification` finding no rule coverage, for the
    session's actual CPQ model(s) -- resolves via the real, per-model
    `blind_fill_risk_accepted_vns` policy table, falling back to the
    legacy `_BLIND_FILL_RISK_ACCEPTED_VNS` membership check when
    `workspace_id`/`product_name` aren't available yet, when no model
    candidates resolve, or when candidate resolution itself fails. Never
    raises. Same contract, same gate, same fallback shape as `resolve_
    optional_empty_fill_membership` -- see its docstring for the full
    safety rationale. Self-resolving (Shape A): every real consumer
    (`multi_fallback.py`, `tier6_single_b.py`, `multi_optout_and_empty.
    py`) has `ctx`/`scope` in local scope but no pre-resolved candidates
    tuple to reuse, unlike the Shape-B resolvers above.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return vn in _BLIND_FILL_RISK_ACCEPTED_VNS
    if workspace_id is None or not product_name:
        return vn in _BLIND_FILL_RISK_ACCEPTED_VNS
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "ModelPolicy resolution failed for vn=%r (ws=%s) -- falling "
            "back to the legacy constant", vn, workspace_id,
        )
        return vn in _BLIND_FILL_RISK_ACCEPTED_VNS
    if not models:
        return vn in _BLIND_FILL_RISK_ACCEPTED_VNS
    return any(vn in blind_fill_risk_accepted_vns(m) for m in models)


def resolve_dt_whitelist_substitute_hiding_rule_name_membership(
    rule_name: str, product_name: str, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> bool:
    """Whether `rule_name` is individually confirmed safe to substitute a
    real Data-Table whitelist check for a missing BmFunction script, for
    the session's actual CPQ model(s) -- resolves via the real, per-model
    `dt_whitelist_substitute_hiding_rule_names` policy table, falling
    back to the legacy `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES`
    membership check when `workspace_id`/`product_name` aren't available
    yet, when no model candidates resolve, or when candidate resolution
    itself fails. Never raises. Same contract, same gate, same fallback
    shape as `resolve_optional_empty_fill_membership` -- see its
    docstring for the full safety rationale. Self-resolving (Shape A):
    its one real consumer, `_load_type11_hiding_rules`, has no
    pre-resolved candidates tuple in scope (unlike the Shape-B resolvers
    above).
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return rule_name in _DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES
    if workspace_id is None or not product_name:
        return rule_name in _DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "ModelPolicy resolution failed for rule_name=%r (ws=%s) -- "
            "falling back to the legacy constant", rule_name, workspace_id,
        )
        return rule_name in _DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES
    if not models:
        return rule_name in _DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES
    return any(
        rule_name in dt_whitelist_substitute_hiding_rule_names(m) for m in models
    )


def resolve_known_sibling_pairs(
    legacy_members: "tuple[tuple[str, str], ...]", product_name: str,
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> "tuple[tuple[str, str], ...]":
    """The disclosed sibling-pair exceptions for the session's actual CPQ
    model(s) -- resolves via the real, per-model `known_sibling_pairs`
    policy table, falling back to `legacy_members` when `workspace_id`/
    `product_name` aren't available yet, when no model candidates
    resolve, or when candidate resolution itself fails. Never raises.

    Unlike a plain vn-membership resolver, this returns a COLLECTION:
    the union of every resolved candidate model's disclosed pairs,
    de-duplicated and order-preserving -- a pair disclosed for any one
    candidate is still real, confirmed information, same "any candidate
    confirms" semantics as the boolean resolvers' `any(...)` check.

    Self-resolving (Shape A): its one real consumer, `exclusive_sibling_
    family_exclusions`, has no pre-resolved candidates tuple in scope,
    so this resolves its own via `product_name` (same as `resolve_
    optional_empty_fill_membership`). `legacy_members` is a parameter,
    not an import, for the same override-preservation reason as
    `resolve_recommended_config_only_membership` -- `CpqEngine.
    _KNOWN_SIBLING_PAIRS` is a class attribute read off the instance,
    and a subclass/instance override must still be honored when the
    gate is off.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return legacy_members
    if workspace_id is None or not product_name:
        return legacy_members
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "ModelPolicy resolution failed for known_sibling_pairs "
            "(ws=%s) -- falling back to the legacy constant", workspace_id,
        )
        return legacy_members
    if not models:
        return legacy_members
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in models:
        for pair in known_sibling_pairs(m):
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    return tuple(pairs)


def resolve_confirmed_dead_attr_membership(
    vn: str, legacy_members: frozenset[str], cpq_models: "tuple[str, ...] | None",
) -> bool:
    """Whether `vn` is a confirmed orphaned/dead attr (real Data-Table-
    driven suppression, not "silently unconfirmed") for the session's
    actual CPQ model(s) -- resolves via the real, per-model
    `confirmed_dead_attrs` policy table, falling back to
    `legacy_members` when no model candidates are available.

    Same shape as `resolve_recommended_config_only_membership`: does
    NOT resolve its own model candidates -- its one real caller
    (`_suppress_ungoverned_attrs`) already computes them unconditionally
    via the pre-existing, separately-cached `_cpq_model_candidates`
    (not gated -- this has always been the case, long before this
    audit's work). `legacy_members` is passed by the caller (its own
    `_CONFIRMED_DEAD_ATTRS`) rather than imported here -- that module
    already imports FROM this one (`resolve_confirmed_dead_attr_
    membership` itself), so importing the constant back would create a
    genuine circular import; this is a deliberate design choice to
    avoid it, not an override-preservation concern like the
    `CpqEngine` class-attribute case.

    Gated behind `model_policy_scoped_resolution_enabled` (same flag
    as every other resolver in this module) -- when off, or when no
    candidates were resolved, behaves byte-identically to today's
    `vn in _CONFIRMED_DEAD_ATTRS` check.
    """
    if not get_settings().model_policy_scoped_resolution_enabled:
        return vn in legacy_members
    if not cpq_models:
        return vn in legacy_members
    return any(vn in confirmed_dead_attrs(m) for m in cpq_models)
