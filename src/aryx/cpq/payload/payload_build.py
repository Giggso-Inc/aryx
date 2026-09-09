"""Orchestrator for `build_payload` (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline body.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.payload.payload_array_sets import group_array_set_rows
from aryx.cpq.payload.payload_multi import serialize_multi_attrs
from aryx.cpq.payload.payload_order import order_payload_keys
from aryx.cpq.payload.payload_scalar import serialize_scalar_attrs
from aryx.cpq.payload.payload_setup import build_context


def build_payload(
    engine: Any,
    filled: dict[str, str],
    filled_source: dict[str, str] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    attrs: list[Any] | None = None,
    hidden_vns: set[str] | None = None,
    rules: list[Any] | None = None,
    display_order: dict[str, int] | None = None,
    product_quantity: int | None = None,
    scope_required_and_edited: bool = False,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
) -> dict[str, Any]:
    """Return the final CPQ BOM API payload as ``{"configData": {...}}``.

    workspace_id / catalog_prefix — optional (default `None`/`""`, no-op
    for every existing caller). Only consulted when
    `scope_required_and_edited` is True, to compute
    `_data_table_resolved_anchor_vns` (docs/CPQ_ConfigData_Payload_
    Mandatory_Fix_Scope_2026_08_19.md) — excludes an anchor-named
    attribute (e.g. modelSelectionbaseModel_astro) from `config_data`
    when it is genuinely resolved by the ingested NewCountryRegMapping
    Data Table rather than a real customer decision. Never affects
    beautify's/the summary's own Tier A behavior.
    scope_required_and_edited — opt-in (default False, preserving every
    existing caller's behavior byte-for-byte). When True, restricts
    config_data to only `_is_mandatory_input_attr`'s Tier A/B set —
    structurally-required decision anchors plus attributes the customer
    directly answered. Everything else (cosmetic auto-fills, blind-picked
    defaults) is excluded from config_data, though it still exists in
    `filled`/`filled_multi` for beautify/summary purposes elsewhere.
    Deliberately NOT wired into the real-submission call path — only
    JSON-preview should ever pass True; a real BOM submission stays
    unscoped/full.
    product_quantity — the session-level order quantity, added as a
    top-level ``"quantity"`` key SIBLING to ``configData`` (never inside
    it — that dict is a mirror of real catalog variable_names only,
    never a synthetic key). Live-verified gap, 2026-08-13: the overall
    order quantity reached the human-readable text summary but never
    the actual submitted JSON payload at all. Strictly opt-in — omitted
    entirely (not even a null key) when not supplied, so this can never
    change the payload shape for any existing caller that doesn't pass it.
    display_order — optional {variable_name: rank} from
    `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
    PLAN.md §2). When supplied, applied as a FINAL filter+resort after
    every other rule below — restricts the payload to exactly the attrs
    present in the map (the catalog's real native-UI visible set) and
    orders them by rank, winning over the dependency-topo-sort/order_number
    tie-break described for `rules` below (every attr that survives this
    filter is, by construction, a real layout member with a real rank).
    `None` (the default) keeps today's behavior — every other
    exclusion/ordering rule below unchanged. Root key is ``configData``
    per the actual integration contract — previously
    ``configAttributes``, an internal assumption never matched by the
    consumer.
    hidden_vns — variable_names an active hiding rule currently matches
    (from ``apply_hiding_rules``' third return value, computed by the
    caller against the exact same ``filled``/rules this turn already
    loaded). When set, these are excluded from the payload even if present
    in ``filled`` — this is the auto-fix side of the hiding-type
    rule-consistency check (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    §4.1): a hidden attr's value was never a real customer decision, so
    dropping it is a certain, safe correction rather than a guess. This is
    DIFFERENT from constraint/recommendation-type inconsistencies, which
    are surfaced to the user instead of silently auto-fixed (same doc,
    §4.1) — hiding is the one case the engine can be certain about.
    Excludes HTML template values (layout/display fields, not real
    configuration inputs) and underscore-prefixed / integration-noise
    variables (``_is_noise_var`` — session/system fields like
    ``_BM_USER_CURRENCY`` or ``CRM_BILL_COUNTRY``, not real BOM
    selections). A value confirmed by the user against a real menu option
    is valid BY DEFINITION: none-like codes (``NA``, ``0``, ...) survive
    when their provenance is a confirmed source; only unconfirmed
    auto-fills are dropped. filled_multi (select_type=="multi" attrs)
    merges in — see per-type shape below. CpqSession.filled stays
    str-only (CPQ_CASCADE_CONVERSATION_PLAN.md §4).
    attrs — optional; when supplied, per-type serialization matches the
    REAL CPQ BOM API contract (confirmed against the documented payload
    spec, docs/CPQ_RULE_TOOL_FLOW_PLAN.md §15b/16 — every shape below was
    checked against a real example, not assumed):
      - hide_in_trans=1 attrs (e.g. productInformationText_astro) are
        excluded entirely — real API rejected both, "cannot be modified".
      - boolean -> bare ``true``/``false`` (no wrapper — real API
        rejected ``{"value": true}`` too, only a bare boolean accepted).
      - currency -> ``{"value": <float>, "currency": <code>}`` (code from
        ``_BM_USER_CURRENCY`` in ``filled`` when present, else "USD" —
        no other currency signal exists in this catalog's own data).
      - integer / float -> bare numeric value; date -> bare string value
        (already in the source's own date format, no reformatting).
      - single-select menu (attr has real options) -> ``{"value":..,
        "displayValue":..}`` — previously missing ``displayValue``.
      - multi-select menu -> ``{"items": [{"value":.., "displayValue":..},
        ...]}`` — previously a bare list of value strings (``{"value":
        [...]}``), a materially different shape than the API documents,
        a SEPARATE bug from the filled-vs-filled_multi routing fixed
        earlier.
      - plain text / no matching ConfigAttr found -> bare string.
    Omitting attrs preserves the EXACT prior behavior (every value
    wrapped as ``{"value": v}``) for existing callers not passing it —
    the per-type behavior above only applies when a ConfigAttr for that
    variable_name is actually available.
    rules — optional combined iterable of HidingRule/ConstraintRule/RecommendationRule
    (any mix; each only needs condition_attr_id, target_attr_id, and optionally
    conditions). When supplied, the final key order is a dependency-aware topological
    sort — an attr gated by another (e.g. Product's allowed values restricted by
    Hardware Version, per a real declarative constraint rule) is placed AFTER the attr
    that gates it, never before. bm_config_attr's own order_number (ConfigAttr.order,
    used below when rules is omitted) reflects catalog UI/display layout only —
    confirmed live it can directly contradict a rule-proven dependency (a target ranked
    far ahead of its own gating condition) — so it is used here only as the tie-break
    between attrs with no dependency relation to each other, not as the primary signal.
    Only DECLARATIVE conditions (conditions/condition_attr_id) contribute edges; script-
    backed rules (script/condition_script set, condition_attr_id==0) have no single
    extractable condition attr and fall back to the order_number tie-break, same as an
    attr with no rule-derived ordering constraint at all — never guessed. A cycle (rule
    data conflict) never drops a key: anything left after the topological pass is
    appended, sorted by order_number, same fallback as no-`rules`-supplied behavior.
    Catalog-agnostic — no attribute or rule name is hardcoded; works for any ingested BM
    export.
    """
    ctx = build_context(
        engine, filled, filled_source, filled_multi, attrs, hidden_vns, rules,
        scope_required_and_edited, workspace_id, catalog_prefix,
    )
    serialize_scalar_attrs(engine, ctx, filled, scope_required_and_edited)
    serialize_multi_attrs(engine, ctx, filled_multi, scope_required_and_edited)
    group_array_set_rows(ctx, attrs, filled)
    ordered_keys = order_payload_keys(engine, ctx, rules, display_order)

    result: dict[str, Any] = {"configData": {k: ctx.out[k] for k in ordered_keys}}
    if product_quantity is not None:
        result["quantity"] = product_quantity
    return result
