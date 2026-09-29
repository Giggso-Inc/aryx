"""``exclusive_sibling_family_exclusions`` -- the generic wrong-sibling
detector (Phase 4 step 7 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Takes the ``engine`` instance: it reaches back for
``_normalized_label_stem`` and for the ``_KNOWN_SIBLING_PAIRS`` class
attribute, both deliberately still on ``CpqEngine``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.model_policy import resolve_known_sibling_pairs
from aryx.cpq.state import ConfigAttr

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.engine import CpqEngine

_WEAK_SOURCES = {"default", "rule", "auto"}


def exclusive_sibling_family_exclusions(
    engine: CpqEngine,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    filled_source: dict[str, str],
    all_attrs: list[ConfigAttr] | None = None,
    catalog_confirmed_vns: frozenset[str] | None = None,
    product_name: str = "",
    workspace_id: int | None = None,
    catalog_prefix: str = "",
) -> tuple[set[str], list[ConfigAttr]]:
    """Generic (no catalog/attribute names hardcoded) detector for a gap
    this engine can hit on ANY catalog: two attrs sharing the same
    real-world concept (near-identical display label, e.g. "Frequency
    Bands" vs "Frequency Band"), one select_type=="multi" and the other
    not, that BOTH ended up filled in the same turn -- meaning no
    catalog hiding rule actually excluded either one for the current
    product (confirmed live on the APX Next catalog, docs/
    config_consistency_issues_2026-07-30.md Issue 5: the active hiding
    rule for this catalog's single-select sibling omits some product
    values entirely, so it stays visible and gets an unconditional
    default_value even when the multi-select sibling is the real
    governing attribute for that product).

    Only acts when the single-select sibling's value came from a
    NON-customer-confirmed provenance -- an unconditional XML
    default_value, an engine-derived recommendation, or the
    conservative auto/first-option fallback (filled_source in
    {"default", "rule", "auto"}) -- never "user"/"hint"/"cascade", so a
    genuine customer-confirmed or customer-triggered value is never
    second-guessed. Widened beyond a bare "default" check (confirmed
    live: this catalog's single-select sibling is actually populated by
    a shared-input RECOMMENDATION rule -- tagged source "rule" -- not a
    bare XML default_value, so a "default"-only check never caught it).

    `all_attrs` (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
    2026_08_05.md follow-up) -- the label-stem grouping below only
    trusts a pair when EXACTLY 2 attrs share that stem, specifically
    so a genuinely ambiguous 3+-way label collision is never guessed.
    That size check is meaningless if it only sees `attrs` (the
    DYNAMICALLY hiding-filtered, currently-visible set): confirmed
    live, a real catalog reuses the identical display label "Service
    Type" across 4 semantically UNRELATED attributes (general service
    type, related-services type, DMS coverage plan, RSM warranty
    type); when a hiding rule happens to leave only 2 of the 4
    visible this turn, the size-2 check wrongly treated them as a
    genuine near-duplicate pair -- the same false-positive class this
    check exists to prevent, just reached via visibility instead of
    catalog authoring. Groups by stem over `all_attrs` (the full,
    pre-hiding catalog list) when given; defaults to `attrs` (old
    behavior, unchanged) when omitted, so every existing caller/test
    is unaffected.

    `catalog_confirmed_vns` -- optional (default `None`, no-op for every
    existing caller). Confirmed live (2026-08-20, base model
    H55TGT9PW8AN/APX NEXT All Band, 4G-only flow): this weak-source
    strip fires even when the single-select's value was itself just
    resolved via the real Whitelist/Defaultinattr Data Table or a
    RecommendationRule triggered by an active decision (source tagged
    "rule"/"default", same as a genuine blind pick) -- for a 4G-only
    product the multi-select sibling has zero legal Data Table rows,
    so stripping the single-select's catalog-proven answer and asking
    for the multi-select instead leaves BOTH empty. Callers pass the
    union of `_rule_forced_from_active_decision_vns`/`_data_table_
    forced_vns` here so a member already proven genuine by either
    mechanism is exempted from this strip -- narrow, catalog-agnostic
    (no attribute name hardcoded), and leaves the 5G flow (where the
    multi-select IS the real governing attr) untouched.

    `product_name`/`workspace_id`/`catalog_prefix` (2026-09-25,
    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3) -- resolve
    `engine._KNOWN_SIBLING_PAIRS` through model_policy for the
    session's actual CPQ model(s), falling back to the hardcoded class
    attribute when unavailable. All default to ""/None (legacy
    behavior byte-identical) so every existing caller keeps working
    unchanged.

    Returns (vns_to_strip_from_filled, attrs_to_add_to_pending) -- the
    multi-select sibling is asked instead of silently guessing which
    half applies. Empty on any catalog without this exact shape.
    """
    by_vn = {a.variable_name: a for a in attrs}
    stem_universe = all_attrs if all_attrs is not None else attrs
    by_stem: dict[str, list[ConfigAttr]] = {}
    for a in stem_universe:
        by_stem.setdefault(engine._normalized_label_stem(a.display_label), []).append(a)
    groups: list[list[ConfigAttr]] = list(by_stem.values())

    # Explicit, disclosed exception -- NOT a generic mechanism. The
    # label-stem detector above provably cannot pair these two: live-
    # confirmed the display labels are "Wireless Carrier" vs "Carrier
    # Selection" (zero shared tokens), yet they exhibit the EXACT same
    # wrong-sibling bug as the generic-detected Frequency Band pair --
    # confirmed live: wirelessCarrier_astro ends up with a value
    # (e.g. "ATT/FIRSTNET", itself a real, valid option on BOTH
    # attributes' overlapping menus, so bom_gate's provenance check
    # never flags it) while carrierSelectionMultiSelect_astro -- the
    # real governing multi-select for this concept -- stays empty.
    # Named explicitly here (per direct approval) rather than silently
    # extending the generic label heuristic to something it can't
    # actually detect.
    _resolved_sibling_pairs = resolve_known_sibling_pairs(
        engine._KNOWN_SIBLING_PAIRS, product_name, workspace_id, catalog_prefix,
    )
    for vn_a, vn_b in _resolved_sibling_pairs:
        attr_a, attr_b = by_vn.get(vn_a), by_vn.get(vn_b)
        if attr_a is not None and attr_b is not None:
            groups.append([attr_a, attr_b])

    to_strip: set[str] = set()
    to_ask: list[ConfigAttr] = []
    for group in groups:
        if len(group) != 2:
            continue
        multi = [a for a in group if a.select_type == "multi"]
        single = [a for a in group if a.select_type != "multi"]
        if len(multi) != 1 or len(single) != 1:
            continue
        multi_attr, single_attr = multi[0], single[0]
        if multi_attr.variable_name not in by_vn:
            # The multi-select sibling only exists in `all_attrs` (the
            # full, pre-hiding catalog list) -- a real hiding rule has
            # decided it does NOT apply this turn (confirmed live: "Hide
            # Frequency Band Model Selection Attribute for APX NEXT All
            # Band model" correctly hides modelSelectionFrequencyBandMsl_
            # astro for that product). There is no more-specific answer
            # to defer to, so the single-select's value -- weak-sourced
            # or not -- is left alone rather than stripped for nothing;
            # stripping it here previously resurrected a question the
            # engine's own hiding-rule evaluation had already, correctly,
            # decided to never ask.
            continue
        single_has_value = single_attr.variable_name in filled
        multi_has_value = bool(filled_multi.get(multi_attr.variable_name))
        if (
            single_has_value and not multi_has_value
            and filled_source.get(single_attr.variable_name) in _WEAK_SOURCES
            and single_attr.variable_name not in (catalog_confirmed_vns or frozenset())
        ):
            to_strip.add(single_attr.variable_name)
            to_ask.append(multi_attr)
    return to_strip, to_ask
