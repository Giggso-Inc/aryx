"""`build_payload`'s final key-ordering stage (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): dependency-aware topological sort (or
order_number fallback) followed by an optional layout `display_order`
stable resort. Logic unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.payload_state import PayloadContext


def order_payload_keys(
    engine: Any, ctx: PayloadContext, rules: list[Any] | None,
    display_order: dict[str, int] | None,
) -> list[str]:
    if rules:
        ordered_keys = engine._dependency_ordered_keys(list(ctx.out.keys()), ctx.attr_by_vn, rules)
    else:
        # Present in the same order the XML/graph itself defines
        # (bm_config_attr.order_number, loaded into ConfigAttr.order)
        # rather than insertion order from auto_fill's hint/default/
        # rule/fallback passes — the two are unrelated, and callers
        # cross-checking the payload against the raw catalog expect the
        # catalog's own order. Keys with no matching ConfigAttr (e.g.
        # hidddenRecordSeparator_allFamilly) keep their original
        # relative position, sorted after every real attr. See
        # _dependency_ordered_keys' docstring for why order_number
        # alone is not a reliable proxy for true submission sequence —
        # this branch only runs when the caller didn't supply `rules`.
        ordered_keys = sorted(
            ctx.out.keys(),
            key=lambda k: (ctx.attr_by_vn[k].order if k in ctx.attr_by_vn else 10**9),
        )
    if display_order is not None:
        # Live-confirmed gap (2026-08-25, SVX Mounting Type array-set
        # payload): this used to be a hard filter -- `k in display_order`
        # dropped any key ENTIRELY, not just left it unranked. A synthetic
        # key this engine itself invents (e.g. an array-set driver's
        # `array_set_wrapper_key`, "_setmountingTypeArrayset_viSoln") can
        # never appear in a native layout export by construction, so it
        # was always silently erased from the real submission payload
        # once a catalog had a layout file at all -- confirmed live: a
        # customer's actual Mounting Type answer vanished from
        # `configData` entirely, even though `out` correctly held it just
        # one line earlier. Stable-sort instead: known keys rank by the
        # layout's own order, unknown keys keep their relative
        # `ordered_keys` position and sort after every known key -- same
        # "never lose a key" contract `_dependency_ordered_keys` already
        # guarantees for its own leftover/cycle case.
        _original_position = {k: i for i, k in enumerate(ordered_keys)}
        ordered_keys = sorted(
            ordered_keys,
            key=lambda k: (display_order.get(k, len(display_order)), _original_position[k]),
        )
    return ordered_keys
