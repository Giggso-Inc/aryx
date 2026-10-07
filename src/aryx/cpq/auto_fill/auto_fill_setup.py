"""Orchestrator for `auto_fill`'s P0 setup (Phase 4, one of the 8
previously-deferred oversized `CpqEngine` methods, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): builds the `FillContext`/`FillScope` pair
`auto_fill_resolve.resolve_one_attr` is called against for every attr.
Logic unchanged from the original inline block.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.auto_fill.auto_fill_conflict_detection import compute_conflicted_optional_ids
from aryx.cpq.auto_fill.auto_fill_data_table_setup import compute_data_table_setup
from aryx.cpq.auto_fill.auto_fill_recommendation_check import build_rec_by_target, make_satisfied_recommendation
from aryx.cpq.engine import FillContext, FillScope

logger = logging.getLogger(__name__)


def _base_model_narrowing(
    attrs: list[Any], filled: dict[str, str], sources: dict[str, str], display_filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str, dt_cache: dict[tuple[int, str], tuple],
) -> Any:
    """The base model narrowing for this pass, or None (flag off, nothing to narrow, or any failure).

    Needs the derivation flag too: without it the base model would wait for the answers and then be asked from the
    full list anyway. A guess made earlier is reopened so the attribute is asked; an error leaves the fill exactly as
    it was without the feature."""
    settings = get_settings()
    if not (settings.cpq_base_model_narrowing_enabled and settings.cpq_derive_base_model_enabled):
        return None
    try:
        from aryx.cpq.base_model_narrowing import (  # noqa: PLC0415 -- flag-gated
            build_base_model_narrowing, reopen_guessed_values,
        )
        narrowing = build_base_model_narrowing(
            attrs, filled, sources, filled.get("productSelectionProduct_all", ""),
            workspace_id, catalog_prefix, dt_cache)
        reopen_guessed_values(narrowing, filled, display_filled, sources)
        return narrowing
    except Exception:  # noqa: BLE001 -- never fails the fill pass
        logger.debug("cpq: base model narrowing failed; filling without it", exc_info=True)
        return None


def build_fill_context_and_scope(
    engine: Any,
    attrs: list[Any],
    hints: dict[str, str],
    already_filled: dict[str, str] | None,
    constrained_opts: dict[int, list[str]] | None,
    filled_source: dict[str, str] | None,
    governed_ids: set[int] | None,
    already_filled_multi: dict[str, list[str]] | None,
    dropped_multi: dict[str, list[str]] | None,
    rule_governed_ids: set[int] | None,
    country: str | None,
    rec_rules: list[Any] | None,
    negated_vns: set[str] | None,
    skip_always_ask: set[str] | None,
    bml_eval: Any | None,
    validation_rules: list[Any] | None,
    display_order: dict[str, int] | None,
    workspace_id: int | None,
    catalog_prefix: str,
    _dt_cache: dict[tuple[int, str], tuple] | None,
    hiding_rules: list[Any] | None,
    _default_fill_signatures: dict[str, tuple] | None,
    _signature_exclude_vns: frozenset[str] | None,
    grid_declined_vns: frozenset[str] | None,
    product_anchor_hint: str | None = None,
) -> tuple[FillContext, FillScope]:
    dt_cache: dict[tuple[int, str], tuple] = _dt_cache if _dt_cache is not None else {}
    filled: dict[str, str] = dict(already_filled or {})
    filled_multi = already_filled_multi if already_filled_multi is not None else {}
    display_filled: dict[str, str] = {}
    pending: list[Any] = []
    sources = filled_source if filled_source is not None else {}
    governed = governed_ids or set()
    rule_governed = rule_governed_ids if rule_governed_ids is not None else governed
    dropped = dropped_multi if dropped_multi is not None else {}
    # Cascade-invalidated attrs whose CLEARED value was a real user
    # decision (filled_source == "user"), not an auto-fill — these must
    # be re-asked (added to `pending`) rather than silently re-guessed
    # by the blind-fallback branch below (docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 4). Mirrors the same "never silently guess a real decision"
    # principle already applied to product-identifier attrs.
    user_answered_dropped_ids: set[int] = set()

    # Pointer-defaults (Issue 11, docs/CPQ_PRODUCT_SWITCH_ISSUE.md): a
    # default_value that exactly equals ANOTHER attribute's variable
    # name is a REFERENCE the source platform resolves at runtime, not
    # a literal (confirmed live: modelname_all's XML default is the
    # string "_bm_model_variable_name" — BM's own "Set Model Name..."
    # rule copies that runtime model-context attr into it; the export
    # carries only the pointer token). Structural check, no attribute
    # names in code — an exhaustive survey of every ingested catalog
    # found exactly this ONE pattern and zero coincidental literal
    # defaults matching an attr name.
    all_vns = {a.variable_name for a in attrs}

    def is_pointer_default(a: Any) -> bool:
        return (not a.options
                and a.default_value in all_vns
                and a.default_value != a.variable_name)

    rec_by_target = build_rec_by_target(rec_rules)
    attr_by_rule_id = engine._attr_index(attrs) if rec_by_target else {}
    satisfied_recommendation = make_satisfied_recommendation(
        engine, filled, rec_by_target, attr_by_rule_id, bml_eval)

    dt_setup = compute_data_table_setup(
        engine, attrs, filled, country, workspace_id, catalog_prefix, dt_cache, hiding_rules)

    conflicted_optional_ids = compute_conflicted_optional_ids(engine, attrs, governed, rule_governed)

    base_model_narrowing = _base_model_narrowing(attrs, filled, sources, display_filled, workspace_id,
                                                 catalog_prefix, dt_cache)

    ctx = FillContext(
        filled=filled, filled_multi=filled_multi, sources=sources,
        dropped=dropped, dt_cache=dt_cache,
        default_fill_signatures=_default_fill_signatures,
        display_filled=display_filled, pending=pending,
        user_answered_dropped_ids=user_answered_dropped_ids,
    )
    scope = FillScope(
        hints=hints, attrs=attrs, constrained_opts=constrained_opts,
        country=country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules, display_order=display_order,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix,
        product_anchor_hint=product_anchor_hint,
        signature_exclude_vns=_signature_exclude_vns,
        grid_declined_vns=grid_declined_vns, governed=governed,
        rule_governed=rule_governed, rec_by_target=rec_by_target,
        grid_selector_vns=dt_setup.grid_selector_vns,
        bm_region_allow_value=dt_setup.bm_region_allow_value,
        dt_governed_vns=dt_setup.dt_governed_vns,
        missing_data_target_ids=dt_setup.missing_data_target_ids,
        conflicted_optional_ids=conflicted_optional_ids,
        is_pointer_default=is_pointer_default,
        satisfied_recommendation=satisfied_recommendation,
        dt_never_governed_anywhere=dt_setup.dt_never_governed_anywhere,
        base_model_narrowing=base_model_narrowing,
    )
    return ctx, scope
