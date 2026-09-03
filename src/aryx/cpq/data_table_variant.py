"""Detects when a product option's real orderable variant differs from the
one currently selected, per ingested series-mapping-shaped Data Table rows.

Split out of `cpq/data_table_consistency.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from aryx.cpq.data_table_loader import _load_all_tables
from aryx.cpq.data_table_shapes import _attr_op_val_triples, _normalize_label


def resolve_invalid_product_variant(
    item_text: str, item_value: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> str | None:
    """The real childCPQModel this product option maps to under the CURRENT
    `filled` context, from every ingested series-mapping-shaped Data Table
    (e.g. Seriesmodelsmapping.csv) in this workspace -- ONLY when it differs
    from `item_value` (i.e. this option isn't actually the real/orderable
    model here). Returns None when no row's childCPQModelLabel matches this
    option's own `item_text` at all, or none of a matching row's own
    attrN/opN/valN condition triples are ALL satisfied by `filled` (every
    triple with an unsupported op, i.e. anything but "=", never counts as
    satisfied -- never guess), or the matching row's childCPQModel already
    equals `item_value` (genuinely valid here, nothing to hide).

    Confirmed live (2026-08-08): Seriesmodelsmapping's row for
    (modelSelectionRegion_astro="NA", ultimateDestinationCountry="US") maps
    "APX NEXT™ International (Federal)" to childCPQModel "APX NEXT INTL
    FED_future" -- not the live "APX NEXT INTL FED" every other region's row
    for this same product maps to. That's Oracle CPQ's own data saying this
    variant isn't real yet for the US market — the option should not be
    offered. The rule meant to enforce this in the static export
    (util.getConstraintVals against hiddenConstraintMasterString_astro)
    can't, because that master-string attribute is always empty (docs/
    CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §7-§10) --
    this is a second, independent real Data Table with the true answer.
    """
    _, _, _, series_rows, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_text = _normalize_label(item_text)
    for row in series_rows:
        label = row.get("childCPQModelLabel")
        if label is None or _normalize_label(str(label)) != norm_text:
            continue
        triples = _attr_op_val_triples(set(row.keys()))
        if not triples:
            continue
        all_satisfied = True
        for attr_col, op_col, val_col in triples:
            if str(row.get(op_col) or "").strip() != "=":
                all_satisfied = False
                break
            condition_attr = str(row.get(attr_col) or "").strip()
            if not condition_attr or filled.get(condition_attr) != row.get(val_col):
                all_satisfied = False
                break
        if not all_satisfied:
            continue
        child = row.get("childCPQModel")
        if not child:
            continue
        if child == item_value:
            return None
        return child
    return None
