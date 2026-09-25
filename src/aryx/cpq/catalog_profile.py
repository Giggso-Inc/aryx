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
