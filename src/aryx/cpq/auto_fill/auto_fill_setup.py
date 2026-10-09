"""Orchestrator for `auto_fill`'s P0 setup (Phase 4, one of the 8
previously-deferred oversized `CpqEngine` methods, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): builds the `FillContext`/`FillScope` pair
`auto_fill_resolve.resolve_one_attr` is called against for every attr.
Logic unchanged from the original inline block.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aryx.config import get_settings
from aryx.cpq.auto_fill.auto_fill_conflict_detection import compute_conflicted_optional_ids
from aryx.cpq.auto_fill.auto_fill_data_table_setup import compute_data_table_setup
from aryx.cpq.auto_fill.auto_fill_recommendation_check import build_rec_by_target, make_satisfied_recommendation
from aryx.cpq.engine import FillContext, FillScope
from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)


_DEPENDENCY_WARNED = False          # the missing-dependency warning is logged once per process


def _required_ask_vns(
    engine: Any, attrs: list[Any], filled: dict[str, str], filled_multi: dict[str, list[str]],
    sources: dict[str, str], display_order: dict[str, int] | None, workspace_id: int | None,
    catalog_prefix: str, product_anchor_hint: str | None, dt_cache: dict | None,
    bml_eval: Any | None = None,
) -> frozenset[str]:
    """Variable names of the derived required set the fill pass must ask, not guess (flag-gated, failure-safe).

    The set is the one config_data and the summary already use (`derive_required_vns`): attrSequence R, a
    blank-disallow rule that fires, a message-only rule that fires; visible; not filled by the catalog itself; with a
    legal value left. A failure leaves the pass exactly as it was."""
    settings = get_settings()
    if not (getattr(settings, "cpq_required_set_asks_enabled", False) and workspace_id is not None):
        return frozenset()
    if not (getattr(settings, "cpq_required_set_rule_guards_assumed_open", False) is True
            or getattr(settings, "cpq_required_set_guards_assumed_open", False)):
        # A guarded blank-disallow rule (the TER-gated encryption rule) does not fire without it, so the set would be
        # incomplete and the rollout different from the one that was tested: say so once per process and ask nothing extra.
        global _DEPENDENCY_WARNED
        if not _DEPENDENCY_WARNED:
            _DEPENDENCY_WARNED = True
            raven_log("WARN", "P3", "ask.required_set.dependency_missing asks flag needs the rule-guard flag, skipped",
                      context={"selected_option": "skipped", "available_options": ["asked", "skipped"],
                               "reason_code": "REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN_OFF"})
        return frozenset()
    try:
        from aryx.cpq.fill_signature import _fill_signature  # noqa: PLC0415 -- flag-gated
        from aryx.cpq.payload_building.required_set import derive_required_vns  # noqa: PLC0415

        # The set depends on the answers and on where each value came from, so it is reused only for an identical
        # state: the fill passes of one turn that change nothing (dt_cache lives for the turn).
        key = ("required_ask_vns", workspace_id, catalog_prefix, product_anchor_hint or "",
               _fill_signature(filled, filled_multi, {a.entity_id for a in attrs}), tuple(sorted(sources.items())))
        if dt_cache is not None and key in dt_cache:
            return dt_cache[key]
        hidden = {a.variable_name for a in attrs if getattr(a, "hidden", False)}
        hidden |= _rule_hidden_vns(engine, attrs, filled, filled_multi, workspace_id, catalog_prefix,
                                   product_anchor_hint, dt_cache, bml_eval)
        started = time.monotonic()
        all_attrs = _rule_input_attrs(settings, workspace_id, catalog_prefix, dt_cache)
        derived = derive_required_vns(
            engine, attrs, filled, filled_multi, sources, hidden, display_order,
            workspace_id, catalog_prefix, product_anchor_hint or "", dt_cache, rule_required_only=True,
            rule_input_attrs=all_attrs)
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.required_set.derived derived required set computed for asking", context={
                "selected_option": "computed", "available_options": ["computed", "reused"],
                "reason_code": "REQUIRED_SET_ASKS", "required_count": len(derived), "required_vns": sorted(derived)[:20],
                "duration_ms": int((time.monotonic() - started) * 1000)})
        if dt_cache is not None:
            dt_cache[key] = derived
        return derived
    except Exception:  # noqa: BLE001 -- asking more is a nicety, never a reason to break the pass
        logger.debug("cpq: derived required set for asking failed", exc_info=True)
        return frozenset()


def _rule_input_attrs(settings: Any, workspace_id: int, catalog_prefix: str, dt_cache: dict | None) -> list[Any] | None:
    """Flag `cpq_required_set_rules_read_all_attrs_enabled`: the full attribute list the rule inputs are read from. The
    turn cache holds it when this call runs inside `evaluate_rules_loop`; the payload, summary and Beautify calls bring
    their own cache, so they take the loop's latest list for the catalog. None (with a warning once per catalog) when
    neither has it, which leaves the visible list as before."""
    if getattr(settings, "cpq_required_set_rules_read_all_attrs_enabled", False) is not True:
        return None
    from aryx.cpq.rules_loop.full_attrs_registry import full_attrs  # noqa: PLC0415 -- flag-gated

    attrs = (dt_cache or {}).get(("_all_attrs", workspace_id, catalog_prefix)) or full_attrs(workspace_id, catalog_prefix)
    if attrs is None and (workspace_id, catalog_prefix) not in _ALL_ATTRS_MISSING_WARNED:
        _ALL_ATTRS_MISSING_WARNED.add((workspace_id, catalog_prefix))
        raven_log("WARN", "P3", "ask.required_set.all_attrs_missing rule inputs read from the visible list only",
                  context={"selected_option": "visible_only", "available_options": ["all_attrs", "visible_only"],
                           "reason_code": "FULL_ATTR_LIST_UNAVAILABLE", "workspace_id": workspace_id,
                           "catalog_prefix": catalog_prefix})
    return attrs


_ALL_ATTRS_MISSING_WARNED: set[tuple[int, str]] = set()


def _blank_host_attrs(attrs: list[Any], filled: dict[str, str], filled_multi: dict[str, list[str]] | None,
                      declarative_rules: list[Any]) -> dict[str, str]:
    """The attributes the hide check counts as blank (flag `cpq_ask_hide_assumes_blank_host_context_enabled`): free-text
    attributes (selection shape "single" with no menu: numeric, date, currency, boolean and multi-select attributes are
    never included) that the quote does not carry AND that at least one declarative hide rule tests. Customer Type and
    Customer UIN are the host-supplied ones; no other attribute is invented."""
    referenced: set[Any] = set()
    for rule in declarative_rules:
        conditions = getattr(rule, "conditions", None)
        if conditions:
            referenced.update(c[0] for c in conditions)
        else:
            referenced.add(getattr(rule, "condition_attr_id", None))
    return {
        a.variable_name: "" for a in attrs
        if (a.entity_id in referenced or getattr(a, "source_id", None) in referenced)
        and a.variable_name not in filled and not (filled_multi or {}).get(a.variable_name)
        and not getattr(a, "options", None) and getattr(a, "select_type", "") == "single"}


def _rule_hidden_vns(
    engine: Any, attrs: list[Any], filled: dict[str, str], filled_multi: dict[str, list[str]],
    workspace_id: int, catalog_prefix: str, product_anchor_hint: str | None, dt_cache: dict | None,
    bml_eval: Any | None,
) -> set[str]:
    """Attributes a hiding rule hides for the current answers (e.g. Encryption Type on an N-series model). A hidden
    attribute is not on the screen, so it is never asked. Failure-safe: nothing extra is hidden."""
    try:
        from aryx.cpq.catalog_profile import resolve_base_model_vn  # noqa: PLC0415
        from aryx.cpq.rule_trace.rule_trace_state import untraced  # noqa: PLC0415
        base_known = bool(filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, dt_cache), ""))
        blank_host = getattr(get_settings(), "cpq_ask_hide_assumes_blank_host_context_enabled", False) is True
        if not base_known and not blank_host:
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ask.required_set.hidden hide check skipped, base model unknown and the flag is off", context={
                    "selected_option": "skipped", "available_options": ["evaluated", "skipped"],
                    "reason_code": "REQUIRED_SET_HIDE_CHECK_SKIPPED", "base_known": False, "blank_host": False})
            return set()    # master-string hide rules say "hide" while the base model is blank; that is not a decision yet
        rules = engine.load_hiding_rules(workspace_id, catalog_prefix, product_anchor_hint or "")
        hidden: set[str] = set()
        with untraced():        # a query, not a decision: it must not add fired-rule rows to the trace
            if base_known:
                hidden |= set(engine.apply_hiding_rules(
                    attrs, filled, rules, bml_eval, filled_multi, workspace_id=workspace_id,
                    catalog_prefix=catalog_prefix, dt_cache=dt_cache)[2])
            if blank_host:
                # Declarative rules only (a script or master-string rule is never evaluated with invented blanks), with
                # the host-supplied context the quote never carries counted as blank, as the real screen has it.
                declarative = [r for r in rules if not getattr(r, "script", None)]
                blanks = _blank_host_attrs(attrs, filled, filled_multi, declarative)
                hidden |= set(engine.apply_hiding_rules(
                    attrs, {**blanks, **filled}, declarative, None, filled_multi, workspace_id=workspace_id,
                    catalog_prefix=catalog_prefix, dt_cache=dt_cache)[2])
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.required_set.hidden attributes the hide check removed from the asked set", context={
                "selected_option": "evaluated", "available_options": ["evaluated", "skipped"],
                "reason_code": "REQUIRED_SET_HIDE_CHECK", "base_known": base_known, "blank_host": blank_host,
                "rules_total": len(rules), "hidden_count": len(hidden), "hidden_vns": sorted(hidden)[:25]})
        return hidden
    except Exception as exc:  # noqa: BLE001 -- a rule that cannot be read hides nothing
        try:
            raven_log("WARN", "P3", "ask.required_set.hide_check_failed hide rules could not be evaluated, nothing extra hidden",
                      error_code="ARYX_ASK_REQUIRED_SET_HIDE_CHECK_FAILED",
                      context={"selected_option": "skipped", "available_options": ["evaluated", "skipped"],
                               "reason_code": "HIDE_CHECK_EXCEPTION", "error_class": type(exc).__name__, "error": str(exc)[:200]})
            logger.debug("cpq: hiding rules for the required set failed", exc_info=True)
        except Exception:  # noqa: BLE001 -- logging must never break the safety net
            pass
        return set()


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

    required_ask_vns = _required_ask_vns(engine, attrs, filled, filled_multi, sources, display_order,
                                         workspace_id, catalog_prefix, product_anchor_hint, dt_cache, bml_eval)

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
        base_model_narrowing=base_model_narrowing, required_ask_vns=required_ask_vns,
    )
    return ctx, scope
