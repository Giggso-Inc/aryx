"""``auto_fill``'s P2/P3 post-pass helpers (Phase 4, the
`auto_fill_resolve` decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md) -- mechanically extracted alongside the `FillContext`
refactor. P4 (the hardware-before-product reorder) lives in
`auto_fill_hw_order.py`.

`_DECISION_REQUIRED_KEYS` is read off the engine MODULE object (never
patched by any test, but kept consistent with this package's own
convention).
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def resolve_pointer_defaults(
    attrs: list["Any"],
    filled: dict[str, str],
    display_filled: dict[str, str],
    sources: dict[str, str],
) -> None:
    """Pointer-default resolution post-pass (Issue 11): an unfilled
    pointer attr inherits its REFERENCED attribute's value once that
    value exists — reproducing what the source platform's own runtime
    rule does (BM's "Set Model Name to All Product Family attribute
    modelname" copies _bm_model_variable_name into modelname_all).
    If the referenced attr never fills (e.g. APX Next, where the
    model context is ambiguous), the pointer attr stays unfilled —
    the token itself is never shipped as data.

    Mutates `filled`/`display_filled`/`sources` in place (mirrors the
    original inline post-pass in `auto_fill`, extracted mechanically
    as Phase 4 step 3's P2).
    """
    all_vns = {a.variable_name for a in attrs}

    def _is_pointer_default(a: "Any") -> bool:
        return (not a.options
                and a.default_value in all_vns
                and a.default_value != a.variable_name)

    for attr in attrs:
        vn = attr.variable_name
        if vn in filled or not _is_pointer_default(attr):
            continue
        ref_value = filled.get(attr.default_value)
        if ref_value:
            filled[vn] = ref_value
            display_filled[vn] = display_filled.get(attr.default_value, ref_value)
            sources.setdefault(vn, "cascade")


def cascade_fill_pending(
    pending: list["Any"],
    filled: dict[str, str],
    display_filled: dict[str, str],
    sources: dict[str, str],
) -> list["Any"]:
    """Cascade fill: for any pending free-text attr that shares a decision
    key fragment with an already-filled attr (e.g. packageRegion ← region
    from modelSelectionRegion_astro), fill it directly from the filled
    sibling. This handles attrs whose item_value is a None sentinel (e.g.
    "NA" = North America but also "na" in _NONE_VALUES) by trusting the
    value that was validated via options on the sibling attr.

    Mutates `filled`/`display_filled`/`sources` in place and returns the
    new `pending` list (mirrors the original inline post-pass in
    `auto_fill`, extracted mechanically as Phase 4 step 3's P3).
    """
    still_pending: list["Any"] = []
    for attr in pending:
        vn_flat_p = attr.variable_name.lower().replace("_", "")
        if attr.options:
            still_pending.append(attr)
            continue
        if attr.select_type == "boolean":
            # A boolean's absent-default state is well-defined (default
            # to "false" — see the governed-boolean fallback above) —
            # never let it fall into the free-text cascade below, which
            # blindly copies ANY same-fragment sibling's raw value with
            # no type check. Confirmed live: a boolean attr named
            # "isUltimateDestinationCountryCA_astro" matched the
            # "country" decision-key fragment and got contaminated with
            # "United States" (a raw string from CRM_BILL_COUNTRY) this
            # way — nonsensical for a true/false field and exactly the
            # payload-shape mismatch the real CPQ API previously rejected.
            filled[attr.variable_name] = "false"
            display_filled[attr.variable_name] = "No"
            sources.setdefault(attr.variable_name, "default")
            continue
        matched_dk = next(
            (dk for dk in _engine_module._DECISION_REQUIRED_KEYS if dk in vn_flat_p), None
        )
        if not matched_dk:
            still_pending.append(attr)
            continue
        # Find a filled sibling that shares this key fragment
        cascaded = next(
            (v for k, v in filled.items()
             if matched_dk in k.lower().replace("_", "") and v),
            None,
        )
        if cascaded:
            filled[attr.variable_name] = cascaded
            display_filled[attr.variable_name] = cascaded
            sources.setdefault(attr.variable_name, "cascade")
        else:
            still_pending.append(attr)
    return still_pending
