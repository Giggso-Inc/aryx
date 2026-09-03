"""Resolves whether/which attributes an ingested sequence-shaped Data Table
governs for a given (CPQModel, BaseModel) -- the applicability question,
distinct from `cpq.data_table_whitelist`'s legal-value question.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from aryx.cpq.data_table_loader import _load_all_tables


def governed_attr_names_for_base_model(
    cpq_model: str, base_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str] | None:
    """Every AttrName any ingested sequence-shaped Data Table lists for
    this exact (cpq_model, base_model) pair -- the set-valued sibling of
    `attribute_applies()`, computed ONCE per (cpq_model, base_model)
    instead of once per (cpq_model, base_model, attr_var_name).

    Confirmed live (2026-08-08): engine.CpqEngine._suppress_ungoverned_
    attrs previously called `attribute_applies()` once per candidate
    attribute (392 in one real catalog) times once per real CPQModel
    candidate for the base model, each call independently re-filtering
    the SAME up-to-47K-row sequence table from scratch. Once base model
    resolution started actually working (a separate fix), this became a
    genuine O(attrs x candidates x rows) cost on every evaluation pass --
    this precomputes the filtered scope once; callers do an O(1) set
    membership check per attribute instead.

    Returns None when no sequence table has ANY row at all for this
    (cpq_model, base_model) -- distinct from a confirmed empty set.
    """
    _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        row for row in sequence_rows
        if row.get("CPQModel") == cpq_model
        and row.get("BaseModel") in (base_model, "ALL")
    ]
    if not scoped:
        return None
    return {row.get("AttrName") for row in scoped if row.get("AttrName")}


def governed_required_attr_names_for_base_model(
    cpq_model: str, base_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str] | None:
    """The Required-only sibling of `governed_attr_names_for_base_model` --
    every AttrName an ingested sequence-shaped Data Table (AttrSequence)
    lists for this exact (cpq_model, base_model) pair with
    optionOrReqFlag == "R" (docs/CPQ_Beautify_Mandatory_Section_
    Miscategorization_2026_08_19.md).

    "R" alone means "must end up with SOME value" -- it does NOT mean
    "genuinely asked to the customer as Mandatory User Input". Many R-
    flagged attrs are auto-resolved by a Whitelist/Defaultinattr row
    (both pooled into the same constraint-shaped `_load_all_tables`
    bucket) rather than ever being a live decision -- callers using this
    for a "Mandatory User Input" classification MUST additionally check
    `resolve_whitelist_values(...) is None` per candidate attribute (i.e.
    no constraint-shaped row resolves it) before treating it as a genuine
    customer-facing Mandatory field. This function only answers the R/O
    question; it does not attempt the second, data-table-coverage check.

    Returns None under the same "no sequence coverage at all for this
    (cpq_model, base_model)" condition `governed_attr_names_for_base_model`
    uses -- distinct from a confirmed empty set.
    """
    _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        row for row in sequence_rows
        if row.get("CPQModel") == cpq_model
        and row.get("BaseModel") in (base_model, "ALL")
    ]
    if not scoped:
        return None
    return {
        row.get("AttrName") for row in scoped
        if row.get("AttrName") and row.get("optionOrReqFlag") == "R"
    }


def attr_ever_governed_for_cpq_model(
    cpq_model: str, attr_var_name: str,
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> bool:
    """True if ANY sequence-shaped Data Table row for this CPQModel -- at
    ANY base model, not just the one currently active -- ever mentions
    `attr_var_name`. Distinguishes two very different reasons an attribute
    can be absent from `governed_attr_names_for_base_model`'s per-base-model
    set:

    1. The catalog tracks this attribute's applicability via sequence rows
       for OTHER base models of this same CPQModel, just not this one --
       a confident "not part of THIS base model" (e.g. wirelessCarrier_
       astro vs carrierSelectionMultiSelect_astro's mutual exclusivity).
    2. The catalog never tracks this attribute via sequence rows for this
       CPQModel at ANY base model at all -- confirmed live (2026-08-09):
       carrierSelectionMultiSelect_astro has real sequence coverage for
       exactly one (CPQModel, BaseModel) pair in the whole ingested
       catalog; every OTHER CPQModel candidate has none, so per-base-model
       absence there is silence, not a confident exclusion.

    Callers should suppress (drop from view) only case 1 -- case 2 has no
    real signal either way and should fall through to "ask the user" with
    the attribute's own real catalog-defined options, matching this
    codebase's never-guess/never-silently-drop convention (docs/CPQ_
    CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §9's own
    "structurally valid but internally contradictory quote is worse than
    an honest ask" reasoning, extended from constraint-fill to visibility).

    Confirmed live (2026-08-09): the first version of this function did a
    fresh `any(... for row in sequence_rows)` scan (up to 46,865 rows) on
    EVERY call -- called once per non-governed attr, per candidate
    CPQModel, per evaluate_rules_loop pass -- reproducing the exact
    O(attrs x candidates x rows) cost `governed_attr_names_for_base_model`
    was already built to eliminate for the per-base-model case. With
    `_invalidate_inconsistent_paired_values` unable to converge for one
    real base model (H55TGT9RW8AN, `inconsistent` stuck at 2), this
    repeated across many passes and drove per-pass cost to 80-325s.
    Precomputes the full per-CPQModel AttrName set ONCE (memoized in
    `cache`, the same per-turn dict every other Data Table lookup here
    already shares), then does an O(1) set-membership check per call --
    same fix shape as `governed_attr_names_for_base_model` itself.
    """
    key = ("_ever_governed_attrs", workspace_id, catalog_prefix, cpq_model)
    if cache is not None and key in cache:
        ever_governed_attrs = cache[key]
    else:
        _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
        ever_governed_attrs = {
            row.get("AttrName") for row in sequence_rows
            if row.get("CPQModel") == cpq_model and row.get("AttrName")
        }
        if cache is not None:
            cache[key] = ever_governed_attrs
    return attr_var_name in ever_governed_attrs


def attribute_applies(
    cpq_model: str, base_model: str, attr_var_name: str,
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> bool | None:
    """Whether `attr_var_name` is governed by this base model at all, per
    every ingested sequence-shaped Data Table in this workspace. Resolves
    the sibling question (e.g. wirelessCarrier_astro vs
    carrierSelectionMultiSelect_astro) with real, catalog-wide data instead
    of one live-session snapshot.

    Returns None when no sequence table has any data at all for this
    (cpq_model, base_model) -- distinct from a confirmed False. A thin
    per-attribute wrapper over `governed_attr_names_for_base_model` --
    callers checking MANY attributes for the same (cpq_model, base_model)
    should call that directly instead, once, rather than this in a loop
    (see its own docstring for the live-measured cost of doing otherwise).
    """
    scoped_names = governed_attr_names_for_base_model(
        cpq_model, base_model, workspace_id, catalog_prefix, cache,
    )
    if scoped_names is None:
        return None
    return attr_var_name in scoped_names
