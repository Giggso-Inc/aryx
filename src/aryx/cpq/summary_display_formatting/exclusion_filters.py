"""Summary/submission exclusion predicates -- "should this filled attr
get a line at all?" (Phase 4 step 10 extraction from ``cpq/engine.py``
-- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

All four are pure predicates over one attr/value. The two submission-
scoped ones (`_attr_hidden_from_submission`,
`_attr_is_transient_set_type`) are the shared single source of truth
`build_payload` and the pre-quote QA listing both call, and
`_is_summary_excluded` mirrors those same two checks so the summary can
never show a line for a field that will never be submitted.

The class-level constants these read (`_BOOLEAN_DISPLAY_VALUES`,
`_YEAR_VALUE_RE`) stay on ``CpqEngine``, reached through the passed-in
`engine` instance so any patch of them still applies at call time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _is_noise_var(variable_name: str) -> bool:
    """True for underscore-prefixed or integration/system-prefixed vars.

    Structural, not name-list-based (§3e): an underscore prefix, or a
    leading `_`-delimited segment that is fully uppercase (e.g.
    `CRM_BILL_COUNTRY`) — the same shape live data showed for
    integration fields, derived from casing convention rather than a
    hardcoded prefix list.
    """
    if variable_name.startswith("_"):
        return True
    head = variable_name.split("_", 1)[0]
    return len(head) >= 2 and head.isalpha() and head.isupper()


def _attr_hidden_from_submission(attr: "ConfigAttr") -> bool:
    """True for hide_in_trans=1 attrs — excluded from every real BOM
    submission (the API rejects these with "cannot be modified" when
    included; see ConfigAttr.hide_in_trans). Single source of truth
    for this exclusion — `build_payload`'s own per-key loop and any
    other caller needing the same answer (e.g. the pre-quote QA
    "list the attributes" answer, `_build_catalog_attribute_listing_
    text` in ask_api.py) both call this instead of re-deriving it,
    so the two can never drift apart.
    """
    return attr.hide_in_trans


def _attr_is_transient_set_type(attr: "ConfigAttr") -> bool:
    """True for a genuinely transient set_type=="2" UI/action-layer
    attr — excluded from every real BOM submission UNLESS auto_lock=1
    (build_payload's own documented exception; see ConfigAttr.set_type
    / ConfigAttr.auto_lock). Single source of truth for this
    exclusion, shared the same way as `_attr_hidden_from_submission`
    above.
    """
    return attr.set_type == "2" and not attr.auto_lock


def _is_summary_excluded(
    engine: Any, variable_name: str, display_label: str, value: str,
    attr: "ConfigAttr | None", source: str | None = None,
    is_mandatory: bool = False, keep_value_shapes: bool = False,
) -> bool:
    """True when a filled attr should not get a summary line.

    Boolean-shaped values (yes/no/true/false, or select_type=="boolean")
    are excluded even when user-chosen — the ask was to only surface
    substantive selections. Secondary-* attrs (inactive duplicates like
    the secondary SIM) and warranty attrs are excluded by name; warranty
    must also match the VALUE ("Service Type → 1 Year Standard
    Warranty" carries the word only there). Product/product-line attrs
    are excluded too — the summary header already names the product, so
    those lines are redundant; they must match the VARIABLE NAME as
    well (`productLineName`, `bm_prd_level_product_line`, ...) because
    several carry labels without the word. Duration-shaped values
    ("1 Year", "3 Years") are excluded as well — subscription terms,
    not configuration choices.

    `is_mandatory` — optional (default `False`, preserving today's
    behavior byte-for-byte). 2026-08-19 fix (docs/CPQ_Beautify_
    Mandatory_Section_Miscategorization_2026_08_19.md): the boolean-
    value/select_type exclusion above was unconditionally dropping
    genuine Mandatory User Input fields with a literal Yes/No answer
    (e.g. isProvisioningRequiredInCloudEnv_astro) from BOTH the
    summary and beautify's full-detail dump, since this check has no
    caller-type gate the way the later `rule_governed_ids`-scoped
    narrowing does. When the caller has independently confirmed this
    attribute IS Mandatory User Input (`_is_mandatory_input_attr`),
    skip the boolean check — a genuine Yes/No decision is exactly the
    kind of "substantive selection" this exclusion exists to keep,
    not drop. Non-mandatory boolean-valued attrs are unaffected.

    `keep_value_shapes` — optional (default `False`): Beautify's own call with flag
    `cpq_beautify_show_boolean_and_duration_values_enabled` on skips the boolean and duration checks for every
    attribute, so a filled Yes/No or "3 Years" shows as on the real screen. The other exclusions still apply.
    """
    if not is_mandatory and not keep_value_shapes:
        if value.strip().lower() in engine._BOOLEAN_DISPLAY_VALUES:
            return True
        if attr is not None and attr.select_type == "boolean":
            return True
        # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T4: `_YEAR_VALUE_RE`
        # matches the WORD "year"/"years" (subscription-term phrasing
        # like "2 Years"), not a literal calendar year -- this check used
        # to run unconditionally, so a genuine Mandatory User Input field
        # whose real answer happens to contain that word (e.g. a
        # duration-shaped mandatory attribute) was silently dropped from
        # the summary even though it's exactly the kind of substantive,
        # customer-relevant line this function exists to keep -- the same
        # "drops even mandatory fields" class of bug the boolean checks
        # above were already gated against. Moved inside the
        # `not is_mandatory` guard to match that existing precedent;
        # non-mandatory year-shaped values (real subscription-term lines
        # this check targets) are unaffected.
        if engine._YEAR_VALUE_RE.search(value):
            return True
    # Issue 5 items 1/2 (docs/config_consistency_issues_2026-07-30.md):
    # build_payload() already excludes hide_in_trans==1 attrs (the
    # source system's own "don't submit this at transaction time"
    # marker) and set_type=="2" (transient UI/action-layer, non-auto-
    # lock) attrs from the submitted BOM — but the conversational
    # summary never applied the same two checks, so a sales rep could
    # see a line in "Associated Options" for a field that will never
    # actually appear in what gets submitted. Same checks, same attr
    # object already available here — mirrors build_payload exactly,
    # no separate exclusion set needed for these two.
    if attr is not None and attr.hide_in_trans:
        return True
    if attr is not None and attr.set_type == "2" and not attr.auto_lock:
        return True
    if attr is not None and attr.hidden and source != "user":
        # hidden=1 in the raw XML means BigMachines' own UI renders this
        # inline as part of a grid widget rather than as its own summary
        # line (confirmed live: 248 hidden attrs in workspace 14, almost
        # all genuine internal/system fields — _config_operation_context,
        # customerUIN, subscriptionStatus_all — never customer-answered).
        # But a grid-quantity companion (e.g.
        # mountingTypeLockingMolleMountQuantity_viSoln) IS hidden=1 yet
        # still gets asked and answered directly in this chat interface,
        # which has no grid rendering to fall back on — excluding it
        # silently dropped the one number the customer actually gave
        # (confirmed live: "15" survived in `filled`/the real payload,
        # just never shown back to them). Only user-sourced answers get
        # this carve-out; rule/default-filled hidden attrs stay excluded.
        return True
    label_l = display_label.lower()
    if "secondary" in label_l:
        return True
    if "warranty" in label_l or "warranty" in value.lower():
        return True
    if variable_name == "productSelectionProduct_all":
        # Exempted from the "product" exclusion below: that rule
        # assumes "the summary header already names the product," but
        # the header shows the internal BOM codename (e.g. "aSTRO25_
        # bom"), never the real, customer-facing product name — this
        # IS that real name (confirmed live: "APX NEXT Enhanced" was
        # silently missing from every summary despite being correctly
        # filled). Every other product/product-line attr this
        # exclusion targets (productLineName, bm_prd_level_product_
        # line, ...) stays excluded.
        return False
    return "product" in label_l or "product" in variable_name.lower()
