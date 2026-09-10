"""`_is_mandatory_input_attr`'s Data-Table-confirmed active-source
widening (Phase 4 step 4 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed.

``_cpq_model_candidates`` and ``dt_resolve_whitelist_values`` are reached
through the ``engine`` MODULE object, never imported by name: several
tests patch them as ``aryx.cpq.engine._cpq_model_candidates`` /
``aryx.cpq.engine.dt_resolve_whitelist_values``, and a
``from aryx.cpq.engine import ...`` here would freeze a pre-patch
reference at import time and silently defeat those patches.
"""

from __future__ import annotations

import time

from aryx.cpq import engine as _engine_module
from aryx.cpq.data_table.data_table_cache import (
    _cache_write_if_marker_unchanged,
    _invalidate_on_marker_change,
)
from aryx.cpq.engine import (
    _ATTRSEQ_CONFIRMED_REQUIRED_VNS,
    _DATA_TABLE_FORCED_VNS_CACHE,
    _DATA_TABLE_FORCED_VNS_CACHE_LAST_SEEN_MARKER,
    _DATA_TABLE_FORCED_VNS_CACHE_TTL_SECONDS,
)


def _data_table_forced_vns(
    filled: dict[str, str], workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
) -> frozenset[str]:
    """`_is_mandatory_input_attr`'s active-source widening for a
    `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` member whose filled value the
    real ingested Whitelist/Defaultinattr Data Table confirms as a
    genuine, catalog-recognized legal option for the active
    (cpq_model, base_model, ...already-filled context) -- not a made-
    up/impossible value. Confirmed live (workspace 93): for base model
    H55TGT9PW8AN + Country=US, wirelessCarrier_astro has TWO real
    legal values (ATT/FIRSTNET, VERIZON) -- deliberately NOT requiring
    exactly one (an earlier, stricter version of this check did, and
    live data proved that too strict: a real catalog-authored choice
    among 2+ legitimate carriers is still a genuine answer the
    customer needs reflected in `config_data`, same as beautify/the
    summary already show it unconditionally for
    `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` members). Catalog-agnostic -- no
    attribute name hardcoded, checks every `_ATTRSEQ_CONFIRMED_
    REQUIRED_VNS` member generically via `resolve_whitelist_values`.

    `filled_multi` -- optional (default `None`). A `_ATTRSEQ_CONFIRMED_
    REQUIRED_VNS` member can be `select_type=="multi"` (e.g.
    carrierSelectionMultiSelect_astro, the 5G-capable sibling of the
    single-select wirelessCarrier_astro) -- its real answer lives in
    `filled_multi`, never in `filled`, so checking `filled.get(vn)`
    alone silently always misses it (confirmed live 2026-08-20: the
    5G flow's carrierSelectionMultiSelect_astro never widened here
    even though the exact same Data Table narrowing this method
    already handled for the 4G single-select sibling applies to it
    too). Confirms via the same `resolve_whitelist_values` legality
    check, requiring every selected value be a real legal option
    (not just one) -- the multi-select analogue of the single-select
    "any real legal option" check above.

    `None`/no `workspace_id`, or no base model resolved yet, is a
    complete no-op -- same convention as every other Data-Table-driven
    helper in this file.
    """
    if workspace_id is None:
        return frozenset()
    base_model = filled.get("modelSelectionbaseModel_astro", "")
    if not base_model:
        return frozenset()
    product = filled.get("productSelectionProduct_all", "")

    _cache_key = (
        workspace_id, catalog_prefix, base_model, product,
        tuple(sorted(
            (vn, filled.get(vn), tuple(sorted((filled_multi or {}).get(vn) or ())))
            for vn in _ATTRSEQ_CONFIRMED_REQUIRED_VNS
        )),
    )
    _marker_at_read = _invalidate_on_marker_change(
        _DATA_TABLE_FORCED_VNS_CACHE, _DATA_TABLE_FORCED_VNS_CACHE_LAST_SEEN_MARKER,
    )
    _hit = _DATA_TABLE_FORCED_VNS_CACHE.get(_cache_key)
    if _hit is not None:
        _ts, _cached_result = _hit
        if time.monotonic() - _ts < _DATA_TABLE_FORCED_VNS_CACHE_TTL_SECONDS:
            return _cached_result

    cands = _engine_module._cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    if not cands:
        return frozenset()
    result: set[str] = set()
    for vn in _ATTRSEQ_CONFIRMED_REQUIRED_VNS:
        val = filled.get(vn)
        multi_vals = (filled_multi or {}).get(vn)
        if not val and not multi_vals:
            continue
        for cm in cands:
            legal = _engine_module.dt_resolve_whitelist_values(
                cm, base_model, vn, filled, workspace_id, catalog_prefix, cache,
            )
            if legal is None:
                continue
            if multi_vals:
                if all(v in legal for v in multi_vals):
                    result.add(vn)
                    break
            elif val in legal:
                result.add(vn)
                break
    _final_result = frozenset(result)
    _cache_write_if_marker_unchanged(
        _DATA_TABLE_FORCED_VNS_CACHE, _cache_key, (time.monotonic(), _final_result), _marker_at_read,
    )
    return _final_result
