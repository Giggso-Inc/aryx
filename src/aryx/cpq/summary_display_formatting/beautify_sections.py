"""The shared (section, label, value) row set behind both Beautify
outputs (Phase 4 step 10 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

One row builder, two renderers (`beautify_text` / `beautify_rows`), so
the plain-text and tabular views can never drift apart on either the
row set or the Mandatory/System section split.

`_filled_summary_triples`, `_is_mandatory_input_attr` and the
`_BEAUTIFY_*_SECTION` constants are all reached through the passed-in
`engine` instance rather than imported, so the original ``self.<name>``
lookups (and any patch of them) behave exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.config import get_settings
from aryx.raven_log import raven_log, would_log

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _drop_rule_hidden(
    triples: list[tuple[str, str, str]], filled_source: dict[str, str] | None,
    workspace_id: int | None, catalog_prefix: str,
) -> list[tuple[str, str, str]]:
    """Flag `cpq_beautify_hide_rule_hidden_enabled`: drop the rows of attributes this request's rules loop hid by rule
    (the real screen does not show them: ws 1267, APX N70 Operation Type and Provisioning Assistance). The customer's own
    answers stay. Without a loop for this catalog in the request, nothing is dropped."""
    if getattr(get_settings(), "cpq_beautify_hide_rule_hidden_enabled", False) is not True:
        return triples
    from aryx.cpq.rules_loop.full_attrs_registry import rule_hidden  # noqa: PLC0415 -- flag-gated

    hidden = rule_hidden(workspace_id, catalog_prefix)
    if not hidden:
        return triples
    sources = filled_source or {}
    kept = [t for t in triples if t[0] not in hidden or sources.get(t[0]) == "user"]
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.beautify.rule_hidden rows hidden by a hiding rule dropped", context={
            "selected_option": "dropped" if len(kept) < len(triples) else "none",
            "available_options": ["dropped", "none"], "reason_code": "RULE_HIDDEN_ROW",
            "dropped_vns": sorted(t[0] for t in triples if t not in kept)[:30], "rule_hidden_count": len(hidden)})
    return kept


def _beautify_sectioned_rows(
    engine: Any,
    product_name: str,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None,
    filled_source: dict[str, str] | None,
    required_vns: frozenset[str] | None = None,
    product_anchor_hint: str | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> list[tuple[str, str, str]]:
    """Shared (section, label, value) rows for beautify_text/beautify_rows.

    When `filled_source` is supplied, splits the output into two
    sections using the SAME `_is_mandatory_input_attr` signal
    `build_payload`'s `scope_required_and_edited` uses to scope
    `config_data` — one scoping key, three consumers (docs/CPQ_
    GOVERNED_BLINDPICK_AND_CONFIGDATA_BEAUTIFY_FIX_PLAN_2026_08_14.md,
    extended 2026-08-19 with Tier C — docs/CPQ_Beautify_Mandatory_
    Section_Miscategorization_2026_08_19.md). This matches native
    Oracle CPQ's own "Mandatory User Input" box vs. everything else,
    instead of one flat, undifferentiated list.

    `filled_source=None` (the default, for existing callers that don't
    pass it) preserves the original single-section behavior exactly —
    every row lands in the Mandatory section so the flat "Product +
    every substantive field" list callers already depend on is
    byte-for-byte unchanged; only callers that opt in by passing
    `filled_source` get the two-section split.

    `required_vns` — optional (default `None`); `mandatory_tier_c_vns`'s
    result, forwarded into `_is_mandatory_input_attr` (Tier C) for the
    split above. Also passed to `_filled_summary_triples` so the
    underlying row set's `_is_summary_excluded` boolean-value gate
    (via `is_mandatory`) sees the same Mandatory classification.

    product_anchor_hint/workspace_id/catalog_prefix/dt_cache — docs/
    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 (all default `None`/
    ``""``, no-op for every existing caller). Forwarded into both the
    shared triples call and this function's own Mandatory/System
    section split below.
    """
    # Flag cpq_beautify_show_boolean_and_duration_values_enabled: keep Yes/No and duration rows (the real screen
    # shows them); passed only when on so the call is unchanged with the flag off.
    shape_kwargs = ({"keep_value_shapes": True}
                    if getattr(get_settings(), "cpq_beautify_show_boolean_and_duration_values_enabled", False) is True
                    else {})
    triples = engine._filled_summary_triples(
        display_filled, attrs, sources=filled_source, required_vns=required_vns,
        product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
        catalog_prefix=catalog_prefix, dt_cache=dt_cache, **shape_kwargs,
    )
    triples = _drop_rule_hidden(triples, filled_source, workspace_id, catalog_prefix)
    attr_by_vn = {a.variable_name: a for a in attrs} if attrs else {}
    rows: list[tuple[str, str, str]] = [
        (engine._BEAUTIFY_MANDATORY_SECTION, "Product", product_name),
    ]
    for var, label, value in triples:
        if filled_source is None:
            section = engine._BEAUTIFY_MANDATORY_SECTION
        else:
            attr = attr_by_vn.get(var)
            section = (
                engine._BEAUTIFY_MANDATORY_SECTION
                if engine._is_mandatory_input_attr(
                    var, attr, filled_source.get(var), required_vns=required_vns,
                    hint_text=product_anchor_hint, workspace_id=workspace_id,
                    catalog_prefix=catalog_prefix, _dt_cache=dt_cache,
                )
                else engine._BEAUTIFY_SYSTEM_SECTION
            )
        rows.append((section, label, value))
    return rows
