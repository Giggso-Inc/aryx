"""CatalogProfile -- per-(workspace, catalog, CPQ model) role resolution.

Phase 3 (T1) of CPQ_Hardcode_Audit_dev_oci_2026-09-25.md. The pilot
slice (Base Model, Region shadow checks, commits 2c3c842a/d12d5eaf)
shipped a free function, `shadow_check_role_vn()`, that independently
resolved CPQ model candidates on every call -- fine for two unrelated,
separately-gated call sites, but not the real `CatalogProfile` design
the audit doc describes ("a CatalogProfile per workspace and catalog,
naming the product, model selector, base model, region, ..."). This
follow-up adds the actual `CatalogProfile` class: one object that
resolves CPQ model candidates ONCE and answers per-role queries against
them, so a future consumer needing more than one role (or the eventual
switch-over from shadow-log to real resolved values) has one coherent
object instead of N independent free-function calls.

`shadow_check_role_vn()` stays as a public, backward-compatible wrapper
around the class -- both already-shipped call sites
(`ask_invalidate_stale_base_model.py`, `payload_building/
anchor_exclusions.py`) keep working unchanged.

Log-only, still: `CatalogProfile.shadow_check()` never changes any
caller's behaviour, exactly like the pilot slice. `resolved_vn()` is
new API surface for a future real switch-over, but nothing calls it
for a real (non-shadow) decision yet.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_product import resolve_variable_name_for_role
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogProfile:
    """Resolved CPQ model candidates for one (workspace, catalog,
    product) triple, plus per-role lookups against them. Construct via
    `CatalogProfile.for_product()`, not directly -- that's the one
    place `_cpq_model_candidates` gets called.
    """

    workspace_id: int
    catalog_prefix: str
    cpq_models: tuple[str, ...]
    cache: dict[tuple, Any] | None = None

    @classmethod
    def for_product(
        cls, product_name: str, workspace_id: int, catalog_prefix: str = "",
        cache: dict[tuple, Any] | None = None,
    ) -> "CatalogProfile":
        """Resolves `product_name`'s CPQ model candidates once (see
        `_cpq_model_candidates`'s own docstring for the 3-tier
        resolution order) and returns a profile scoped to them."""
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
        return cls(
            workspace_id=workspace_id, catalog_prefix=catalog_prefix,
            cpq_models=models, cache=cache,
        )

    def resolved_vn(self, role: str) -> str | None:
        """The real attrToVarMapping-resolved variable_name for `role`,
        trying each of `self.cpq_models` in order and returning the
        first match -- `None` if no candidate model has an
        unambiguous attrToVarMapping row for this role (never a
        guess, matching `resolve_variable_name_for_role`'s own
        never-guess contract)."""
        for model in self.cpq_models:
            resolved = resolve_variable_name_for_role(
                model, role, self.workspace_id, self.catalog_prefix, self.cache,
            )
            if resolved is not None:
                return resolved
        return None

    def resolved_vn_or(self, role: str, literal_vn: str) -> str:
        """The real attrToVarMapping-resolved variable_name for `role`
        when available, falling back to `literal_vn` otherwise --
        CatalogProfile's own priority order, step 4 ("today's literal
        where it exists, keeps APX NEXT identical"). This is the real,
        governing resolution (unlike `shadow_check`, which only
        observes): callers should use this value directly, not compare
        against it. Logs a warning when the resolved value disagrees
        with the literal -- same signal `shadow_check` surfaces, now
        feeding the real decision instead of only observing it. Never
        raises -- a resolution failure (e.g. an RDB error) must never
        break the real path calling this; it just falls back to the
        literal, exactly like "no attrToVarMapping coverage" does."""
        try:
            resolved = self.resolved_vn(role)
        except Exception:
            logger.exception(
                "CatalogProfile resolution failed for role=%r literal=%r "
                "(ws=%s) -- falling back to the literal",
                role, literal_vn, self.workspace_id,
            )
            return literal_vn
        if resolved is None:
            return literal_vn
        if resolved != literal_vn:
            logger.warning(
                "CatalogProfile resolved a different variable_name than "
                "the literal for role=%r: literal=%r resolved=%r (ws=%s "
                "catalog_prefix=%r) -- using the resolved value",
                role, literal_vn, resolved, self.workspace_id, self.catalog_prefix,
            )
        return resolved

    def shadow_check(self, role: str, literal_vn: str) -> None:
        """Best-effort, log-only: for each of `self.cpq_models`,
        compare `literal_vn` against what the real attrToVarMapping
        resolver gives for `role` under that model, logging any
        disagreement. Never raises -- a bug here must never affect
        the real path a caller is shadowing. Checks every candidate
        model (not just the first resolved one, unlike `resolved_vn`)
        since a disagreement on ANY candidate is worth surfacing."""
        try:
            for model in self.cpq_models:
                resolved = resolve_variable_name_for_role(
                    model, role, self.workspace_id, self.catalog_prefix, self.cache,
                )
                if resolved is None or resolved == literal_vn:
                    continue
                logger.warning(
                    "CatalogProfile shadow mismatch: role=%r model=%r literal=%r "
                    "resolved=%r (ws=%s catalog_prefix=%r)",
                    role, model, literal_vn, resolved, self.workspace_id, self.catalog_prefix,
                )
        except Exception:
            logger.exception(
                "CatalogProfile shadow check failed for role=%r literal=%r "
                "(ws=%s) -- ignored, literal path unaffected",
                role, literal_vn, self.workspace_id,
            )


def shadow_check_role_vn(
    role: str, literal_vn: str, product_name: str, workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> None:
    """Backward-compatible free-function wrapper around `CatalogProfile`
    -- both call sites shipped by the pilot slice (`ask_invalidate_
    stale_base_model.py`, `payload_building/anchor_exclusions.py`) call
    this exact signature and are unaffected by the class's addition.
    New callers needing more than one role for the same product should
    build a `CatalogProfile` directly instead, to resolve CPQ model
    candidates once rather than once per role.

    Model-candidate resolution failures are swallowed the same way
    `CatalogProfile.shadow_check` swallows resolution failures --
    `_cpq_model_candidates` itself is not expected to raise under
    normal conditions, but this preserves the pilot slice's original
    never-raise contract regardless.
    """
    try:
        profile = CatalogProfile.for_product(product_name, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "CatalogProfile shadow check failed for role=%r literal=%r "
            "(ws=%s) -- ignored, literal path unaffected",
            role, literal_vn, workspace_id,
        )
        return
    profile.shadow_check(role, literal_vn)


# ---------------------------------------------------------------------------
# Phase 3 "scoped" rollout (T1): real, governing resolution for individual
# roles -- one free function per role, each the SINGLE place its literal is
# declared, so every one of that literal's call sites resolves through the
# same function instead of independently re-declaring the string (the exact
# T10 drift pattern this whole audit is about). Each falls back to today's
# literal whenever resolution is unavailable, so a caller with no
# workspace_id/product yet, or a workspace with no attrToVarMapping
# coverage (confirmed live 2026-09-25: true for every real workspace this
# session could check), behaves identically to before this existed.
# ---------------------------------------------------------------------------

BASE_MODEL_LITERAL = "modelSelectionbaseModel_astro"
# The platform's standard product-selector attribute (the same name every data-table
# resolver here already keys on); defined once so new code does not repeat it.
PRODUCT_LITERAL = "productSelectionProduct_all"


def resolve_base_model_vn(
    filled: dict[str, str] | None, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str:
    """The real key `filled` stores Base Model's value under, for the
    session's actual CPQ model -- resolves via `CatalogProfile.
    resolved_vn_or`, falling back to `BASE_MODEL_LITERAL` when `filled`/
    `workspace_id`/Product aren't available yet, or when the workspace's
    attrToVarMapping data doesn't cover this role. Never raises.

    Every real call site for this literal should go through this one
    function rather than building its own `CatalogProfile` -- keeps
    every site's resolution result identical within one turn (same
    inputs -> same `_cpq_model_candidates` call -> same answer) instead
    of risking independent drift.

    Gated behind `catalog_profile_scoped_resolution_enabled` (default
    off), checked FIRST, before anything else: live-confirmed (a hung
    unit test caught this before it shipped) that an ungated version of
    this function pays a real, uncached ~265s-class RDB round trip on
    its first call in any 300s window -- and this function is now
    called from ~16 sites, several in hot loops (one per rules-loop
    pass). Unconditionally live across that many sites would have been
    a severe latency regression on the very first turn to reach any of
    them, the same class of bug this session already fixed twice
    elsewhere. Off by default until a workspace with real
    attrToVarMapping coverage exists to turn it on for.
    """
    if not get_settings().catalog_profile_scoped_resolution_enabled:
        return BASE_MODEL_LITERAL
    if not filled or workspace_id is None:
        return BASE_MODEL_LITERAL
    product = filled.get("productSelectionProduct_all", "")
    if not product:
        return BASE_MODEL_LITERAL
    try:
        profile = CatalogProfile.for_product(product, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "CatalogProfile resolution failed for role='Base Model' (ws=%s) "
            "-- falling back to the literal", workspace_id,
        )
        return BASE_MODEL_LITERAL
    return profile.resolved_vn_or("Base Model", BASE_MODEL_LITERAL)


REGION_LITERAL = "modelSelectionRegion_astro"


def resolve_region_vn(
    filled: dict[str, str] | None, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str:
    """The real key `filled` stores Region's value under, for the
    session's actual CPQ model -- resolves via `CatalogProfile.
    resolved_vn_or`, falling back to `REGION_LITERAL` when `filled`/
    `workspace_id`/Product aren't available yet, or when the workspace's
    attrToVarMapping data doesn't cover this role. Never raises.

    Same contract, same gate (`catalog_profile_scoped_resolution_
    enabled`), and same reasoning as `resolve_base_model_vn` -- see its
    docstring for the full safety rationale (an ungated version of this
    class of function already caused one hung test this session).
    """
    if not get_settings().catalog_profile_scoped_resolution_enabled:
        return REGION_LITERAL
    if not filled or workspace_id is None:
        return REGION_LITERAL
    product = filled.get("productSelectionProduct_all", "")
    if not product:
        return REGION_LITERAL
    try:
        profile = CatalogProfile.for_product(product, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "CatalogProfile resolution failed for role='Region' (ws=%s) "
            "-- falling back to the literal", workspace_id,
        )
        return REGION_LITERAL
    return profile.resolved_vn_or("Region", REGION_LITERAL)


HIDDEN_MASTER_STRING_LITERAL = "hiddenMasterStringForAstroPortable_astro"


def resolve_hidden_master_string_vn(
    filled: dict[str, str] | None, workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str:
    """The real key `filled` stores the Hidden Master String's value
    under, for the session's actual CPQ model -- resolves via
    `CatalogProfile.resolved_vn_or`, falling back to
    `HIDDEN_MASTER_STRING_LITERAL` when `filled`/`workspace_id`/Product
    aren't available yet, or when the workspace's attrToVarMapping data
    doesn't cover this role. Never raises.

    Unlike Base Model/Region, "Hidden Master String" has no live-
    confirmed attrToVarMapping role label -- this attribute is
    synthetic (computed from the ingested attrSequence Data Table, never
    a real catalog menu item a customer sees), so it may simply never
    resolve to anything in any real catalog. That's fine: the fallback
    contract here is identical either way, and this function exists so
    the code path is ready the moment that assumption is ever proven
    wrong, exactly like `resolve_base_model_vn`/`resolve_region_vn`.

    Same contract, same gate (`catalog_profile_scoped_resolution_
    enabled`), same reasoning as the other two -- see
    `resolve_base_model_vn`'s docstring for the full safety rationale.
    """
    if not get_settings().catalog_profile_scoped_resolution_enabled:
        return HIDDEN_MASTER_STRING_LITERAL
    if not filled or workspace_id is None:
        return HIDDEN_MASTER_STRING_LITERAL
    product = filled.get("productSelectionProduct_all", "")
    if not product:
        return HIDDEN_MASTER_STRING_LITERAL
    try:
        profile = CatalogProfile.for_product(product, workspace_id, catalog_prefix, cache)
    except Exception:
        logger.exception(
            "CatalogProfile resolution failed for role='Hidden Master String' "
            "(ws=%s) -- falling back to the literal", workspace_id,
        )
        return HIDDEN_MASTER_STRING_LITERAL
    return profile.resolved_vn_or("Hidden Master String", HIDDEN_MASTER_STRING_LITERAL)
