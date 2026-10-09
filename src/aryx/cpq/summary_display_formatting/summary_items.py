"""The filtered summary item set: (variable_name, label, value) triples
and the (label, value) pairs derived from them (Phase 4 step 10
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_filled_summary_triples` owns ALL the filtering every other member of
this cluster (pairs, categorization, beautify, render) builds on.

Every collaborator it needs -- `_is_html_value`, `_is_noise_var`,
`_is_summary_excluded`, `_is_mandatory_input_attr` -- is reached back
through the passed-in `engine` instance rather than by importing the
local function, so the original ``self.<name>`` lookups (and any test
that patches those class attributes) behave exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq.constants import NONE_DISPLAY_PLACEHOLDER as _NONE_DISPLAY_PLACEHOLDER

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _filled_summary_triples(
    engine: Any,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    rule_governed_ids: set[int] | None = None,
    sources: dict[str, str] | None = None,
    display_order: dict[str, int] | None = None,
    required_vns: frozenset[str] | None = None,
    product_anchor_hint: str | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
    keep_value_shapes: bool = False,
) -> list[tuple[str, str, str]]:
    """Filtered (variable_name, display_label, value) triples worth
    summarising — same filtering as filled_summary_pairs, but keeps
    variable_name so callers (render_filled_summary's category
    grouping) can pattern-match on it. See filled_summary_pairs for the
    filtering rules this applies.

    display_order — optional {variable_name: rank} from
    `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
    PLAN.md §2). When supplied, restricts to exactly the attrs present
    in the map and sorts by rank instead of `display_filled`'s
    fill-order — the same catalog layout the real native UI shows,
    instead of an incidental artifact of resolution order. `None`
    (the default) keeps today's behavior unchanged.

    required_vns — optional (default `None`); `mandatory_tier_c_vns`'s
    result, forwarded into `_is_mandatory_input_attr` for the
    `rule_governed_ids is not None` (summary-only) branch below and
    into `_is_summary_excluded`'s `is_mandatory` gate. 2026-08-19
    (docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.
    md): the summary's item list now equals EXACTLY the Mandatory
    User Input set (`_is_mandatory_input_attr`, Tier A/B/C) instead of
    its own separately-maintained "rule-governed and actively-sourced"
    narrowing — one shared signal with beautify, so the two can never
    silently drift apart on what counts as Mandatory. `rule_governed_
    ids is None` (beautify's own call shape) is completely unaffected
    by this — that branch never runs.

    product_anchor_hint/workspace_id/catalog_prefix/dt_cache — docs/
    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 (all default `None`/
    ``""``, no-op for every existing caller). Forwarded into both
    `_is_mandatory_input_attr` calls below so the summary's Mandatory
    classification agrees with `build_payload`'s on Hardware Version
    applicability, instead of the two silently drifting apart.

    keep_value_shapes — optional (default `False`); forwarded to `_is_summary_excluded` (Beautify keeps Yes/No and
    duration values, flag `cpq_beautify_show_boolean_and_duration_values_enabled`). Passed only when True.
    """
    if not display_filled:
        return []
    shape_kwargs = {"keep_value_shapes": True} if keep_value_shapes else {}
    by_vn: dict[str, "ConfigAttr"] = {a.variable_name: a for a in attrs} if attrs else {}
    label_map: dict[str, str] = {vn: a.display_label for vn, a in by_vn.items()}
    # Disambiguate a display_label 2+ distinct attrs share (real
    # BigMachines source-data reuse, docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 2) by appending variable_name — otherwise two unrelated rows
    # render as identical, unreadable duplicate lines in the summary.
    _label_counts: dict[str, int] = {}
    for _lbl in label_map.values():
        _label_counts[_lbl] = _label_counts.get(_lbl, 0) + 1
    for vn, lbl in list(label_map.items()):
        if _label_counts.get(lbl, 0) >= 2:
            label_map[vn] = f"{lbl} ({vn})"
    items = [
        (var, label) for var, label in display_filled.items()
        if not engine._is_html_value(label)
        and not engine._is_noise_var(var)
        and not engine._is_summary_excluded(
            var, label_map.get(var, var), label, by_vn.get(var),
            source=(sources or {}).get(var),
            is_mandatory=engine._is_mandatory_input_attr(
                var, by_vn.get(var), (sources or {}).get(var),
                required_vns=required_vns,
                hint_text=product_anchor_hint, workspace_id=workspace_id,
                catalog_prefix=catalog_prefix, _dt_cache=dt_cache,
            ),
            **shape_kwargs,
        )
        # "(none)" is the engine's own literal placeholder for an
        # unfilled multi/array-typed field (e.g. Promotion, Solution
        # Set) — confirmed live: it survives every other filter since
        # it's a real, deliberately-set display value, not noise by any
        # existing rule. Worth summarising nothing, so drop it here.
        and label.strip() != _NONE_DISPLAY_PLACEHOLDER
    ]
    if rule_governed_ids is not None:
        items = [
            (var, label) for var, label in items
            if engine._is_mandatory_input_attr(
                var, by_vn.get(var), (sources or {}).get(var),
                required_vns=required_vns,
                hint_text=product_anchor_hint, workspace_id=workspace_id,
                catalog_prefix=catalog_prefix, _dt_cache=dt_cache,
            )
        ]
    if display_order is not None:
        items = sorted(
            (item for item in items if item[0] in display_order),
            key=lambda item: display_order[item[0]],
        )
    return [(var, label_map.get(var, var), label) for var, label in items]


def filled_summary_pairs(
    engine: Any,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    rule_governed_ids: set[int] | None = None,
    sources: dict[str, str] | None = None,
    display_order: dict[str, int] | None = None,
    required_vns: frozenset[str] | None = None,
    product_anchor_hint: str | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> list[tuple[str, str]]:
    """Filtered (display_label, value) pairs worth summarising.

    Uses display_label (human name) as the key when attrs are supplied,
    falling back to variable_name only when the attr is not found.
    Skips HTML template values (layout/display fields), system/
    integration noise (`_is_noise_var`, §3e), and low-signal lines
    (`_is_summary_excluded`: boolean values, secondary attrs, warranty
    attrs, product/product-line attrs, year-duration values).

    rule_governed_ids — when supplied (i.e. not `None`), the summary's
    item list is narrowed to exactly `_is_mandatory_input_attr`'s
    Mandatory User Input set (Tier A/B/C, see `_filled_summary_
    triples`) — the rest are silently omitted.

    required_vns — forwarded to `_filled_summary_triples`; see its own
    docstring (Tier C, `mandatory_tier_c_vns`'s result).
    """
    return [
        (label, value)
        for _var, label, value in engine._filled_summary_triples(
            display_filled, attrs, rule_governed_ids, sources, display_order,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache,
        )
    ]
