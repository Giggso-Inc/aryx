"""Computing the real, de-duplicated, display-order-ranked attribute-
label list a "list the attributes" answer is scoped to, split out of
`_build_catalog_attribute_listing_text` (Phase 3/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to
keep the sibling `ask_catalog_listing_text.py` under the line cap. Logic
unchanged from the original inline definitions. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any



def _looks_like_raw_variable_name(label: str) -> bool:
    return (
        bool(label) and " " not in label
        and label[0].islower() and any(c.isupper() for c in label[1:])
    )


def _reaches_json_payload(a: Any) -> bool:
    # Layout membership (what the real screen shows) and payload
    # eligibility (what build_payload would actually let through) are
    # orthogonal -- both must hold. Live-confirmed 2026-08-31: the
    # native UI layout export includes action-button-like entries
    # ("Merge", "Update", "Clear", "Select") whose underlying attrs
    # are set_type=="2" transient/action-layer -- real, on-screen
    # controls, but never real submitted data. Skipping this check
    # for the layout-scoped path let them leak back in.
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    return (
        not a.hidden
        and not _cpq_engine._attr_hidden_from_submission(a)
        and not _cpq_engine._attr_is_transient_set_type(a)
        and not _cpq_engine._is_noise_var(a.variable_name)
    )


def _scope_catalog_listing_labels(
    attrs: list, workspace_id: int, catalog_prefix: str,
) -> list[str]:
    """Layout export available (tier 1/2 catalogs, e.g. APX Next, SVX):
    scope to exactly the variable_names it marks `hide: false` /
    non-HTML, ranked by the file's own document order. No layout export
    (tier 3): fall back to `attrs`' own catalog `order`. See
    `_build_catalog_attribute_listing_text`'s own docstring for the full
    rationale. Returns de-duplicated display labels in scope/rank order.
    """
    from aryx.api import ask_api as _ask_api_module
    layout_order = _ask_api_module._cpq_engine.load_layout_display_order(
        workspace_id, catalog_prefix,
    )
    if layout_order:
        visible = sorted(
            (
                a for a in attrs
                if a.variable_name in layout_order
                and a.display_label.strip()
                and not _looks_like_raw_variable_name(a.display_label)
                and _reaches_json_payload(a)
            ),
            key=lambda a: layout_order[a.variable_name],
        )
    else:
        visible = sorted(
            (
                a for a in attrs
                if a.display_label.strip()
                and not _looks_like_raw_variable_name(a.display_label)
                and _reaches_json_payload(a)
            ),
            key=lambda a: a.order,
        )
    # Real catalogs run into the hundreds of attributes (APX Next: ~430
    # total, live-confirmed) -- de-duplicate identical labels (the same
    # label can legitimately appear on several distinct attrs, see
    # detect_label_collision) since the customer-facing LIST only needs
    # the label once, not once per underlying variable_name.
    seen: set[str] = set()
    labels: list[str] = []
    for a in visible:
        if a.display_label not in seen:
            seen.add(a.display_label)
            labels.append(a.display_label)
    return labels
