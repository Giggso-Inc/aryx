"""`build_payload`'s pre-serialization setup (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): array-control-count derivation, array-set
quantity-member linkage, the hidden-attr auto-fix log line, and the
scope_required_and_edited exclusion-set precomputation. Logic unchanged
from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import ConfigAttr, logger
from aryx.cpq.payload.payload_state import PayloadContext


def build_context(
    engine: Any,
    filled: dict[str, str],
    filled_source: dict[str, str] | None,
    filled_multi: dict[str, list[str]] | None,
    attrs: list["ConfigAttr"] | None,
    hidden_vns: set[str] | None,
    rules: list[Any] | None,
    scope_required_and_edited: bool,
    workspace_id: int | None,
    catalog_prefix: str,
    product_anchor_hint: str | None = None,
    dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> PayloadContext:
    sources = filled_source or {}
    attr_by_vn = {a.variable_name: a for a in (attrs or [])}
    hidden = hidden_vns or set()
    ctx = PayloadContext(sources=sources, attr_by_vn=attr_by_vn, hidden=hidden)
    # docs/CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 — carried on ctx so
    # both serialization stages' `_is_mandatory_input_attr` calls can reach
    # the Hardware Version applicability check without a third parallel
    # param list.
    ctx.workspace_id = workspace_id
    ctx.catalog_prefix = catalog_prefix
    ctx.product_anchor_hint = product_anchor_hint
    ctx.dt_cache = dt_cache

    # is_array_control_attr=1 attrs (e.g. mountingArrayControl_viSoln)
    # ARE expected in the real payload — confirmed live against a
    # genuine reference payload (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 3
    # revision) as a BARE int equal to the array-set's row count, not
    # excluded as previously assumed. There is still no ingested link
    # from a control attr to its own selector attr (that requires the
    # bm_config_attr_set ingestion scoped in
    # docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md) — deriving the count by
    # NAME-matching control<->selector would be exactly the guessing
    # resolve_array_grid_links's own docstring already refuses to do for
    # this catalog family. So this only derives a count when the link is
    # STRUCTURALLY unambiguous: exactly one is_array_control attr and
    # exactly one select_type=="multi" attr among the attrs this turn
    # loaded — the count is that multi-select's number of selected
    # values. Any other shape (0 or 2+ of either) abstains rather than
    # guess, same "match or bail" discipline used everywhere else.
    if attrs:
        control_attrs = [a for a in attrs if a.is_array_control]
        multi_attrs = [a for a in attrs if a.select_type == "multi"]
        if len(control_attrs) == 1 and len(multi_attrs) == 1:
            selector_vn = multi_attrs[0].variable_name
            selected = (filled_multi or {}).get(selector_vn) or []
            ctx.array_control_count = len(selected)

    # Real per-option quantity attrs feeding an array-set's own qty
    # member column (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md, quantity-
    # nesting gap): mountingTypeArrayqty_viSoln-style array-set qty
    # members are NEVER themselves populated by the real conversation
    # flow — resolve_pending_grid_quantities fills the per-option NAMED
    # attrs instead (e.g. mountingTypeLockingMolleMountQuantity_viSoln,
    # confirmed live against real workspace-19 sessions). Computed once,
    # before either serialization loop below, so both the flat scalar
    # loop (which must SKIP these, not ship them standalone) and the
    # array-set grouping pass (which folds their value into the row
    # under the qty member's own key name) agree on the same mapping.
    ctx.grid_links = engine.resolve_array_grid_links(attrs or [])
    if attrs:
        _by_set: dict[int, list[ConfigAttr]] = {}
        for a in attrs:
            if a.array_set_id is not None and a.array_set_role == "member":
                _by_set.setdefault(a.array_set_id, []).append(a)
        for _members in _by_set.values():
            _selector = next((a for a in _members if a.options), None)
            _qty_member = next((a for a in _members if not a.options), None)
            if not _selector or not _qty_member:
                continue
            for _qty_vn in ctx.grid_links.get(_selector.variable_name, {}).values():
                ctx.array_set_qty_source[_qty_vn] = _qty_member.variable_name
                ctx.consumed_by_array_set.add(_qty_vn)

    if hidden:
        dropped = [k for k in filled if k in hidden and filled[k]]
        if dropped:
            logger.info(
                "cpq: build_payload auto-fix — dropping %s (active hiding rule matches, "
                "rule-consistency check — docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1)",
                dropped,
            )

    # Only computed when actually needed -- avoids the resolver cost
    # for every caller that doesn't opt into scope_required_and_edited.
    ctx.exclude_anchor_vns = (
        engine._data_table_resolved_anchor_vns(filled, attrs, workspace_id, catalog_prefix)
        if scope_required_and_edited else frozenset()
    )
    ctx.rule_forced_active_vns = (
        engine._rule_forced_from_active_decision_vns(
            rules, attrs, sources, engine._CONFIG_DATA_ACTIVE_SOURCES,
        )
        if scope_required_and_edited else frozenset()
    )
    ctx.data_table_forced_vns = (
        engine._data_table_forced_vns(
            filled, workspace_id, catalog_prefix, filled_multi=filled_multi,
        )
        if scope_required_and_edited else frozenset()
    )
    return ctx
