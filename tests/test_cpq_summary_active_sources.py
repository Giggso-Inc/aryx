"""Regression coverage for the summary's item-selection contract.

2026-08-19 update (docs/CPQ_Beautify_Mandatory_Section_Miscategorization_
2026_08_19.md): the summary's item list previously used its own,
separately-maintained narrowing (rule_governed_ids membership + an
active-source check + a curated Associated-Options fragment filter). That
mechanism is now REMOVED — the summary's item list equals EXACTLY
`_is_mandatory_input_attr`'s Mandatory User Input set (Tier A/B/C), the
same signal beautify and (for a narrower Tier A/B-only slice)
`build_payload`'s `config_data` use — one shared signal, so none of the
three consumers can silently drift apart on what counts as "genuinely
required." A `rule_governed_ids is not None` call (even an empty set) now
means "apply the Mandatory-set filter", not "narrow to this specific
static rule-target set."

Practical consequence some of these tests document: a `source == "rule"`
value (a rule that genuinely fired) is NO LONGER included in the summary
by default — that's exactly a "cosmetic auto-fill"/"catalog-computed"
value, not a customer decision, matching `config_data`'s own contract
(docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md). It only
re-appears via Tier C (`required_vns`, `mandatory_tier_c_vns`'s result)
when the attribute is genuinely AttrSequence-Required, not curated
Recommended-only, and not resolvable by any Whitelist/Defaultinattr row.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(entity_id, variable_name, display_label):
    return ConfigAttr(
        entity_id=entity_id, variable_name=variable_name,
        display_label=display_label, required=False, default_value="",
        options=[],
    )


def test_summary_excludes_rule_governed_attr_with_a_bland_default_source():
    eng = CpqEngine()
    attrs = [_attr(1, "packages_astro", "Packages")]
    display_filled = {"packages_astro": "Gold"}
    rule_governed_ids = {1}
    sources = {"packages_astro": "default"}  # nobody reasoned about it THIS turn

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_excludes_rule_sourced_attr_even_when_rule_actually_fired():
    """2026-08-19 update: a fired-rule value is exactly the "cosmetic
    auto-fill" the Mandatory-set filter excludes by default — it is
    NOT a customer decision, regardless of whether some rule reasoned
    about it this turn. It only survives via Tier C (see the sibling
    test below), never via source=="rule" alone."""
    eng = CpqEngine()
    attrs = [_attr(1, "solutionTypeDevices_astro", "Solution Type")]
    display_filled = {"solutionTypeDevices_astro": "RadioCentral with CPS"}
    rule_governed_ids = {1}
    sources = {"solutionTypeDevices_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_includes_rule_sourced_attr_via_tier_c():
    """The sibling of the test above: a rule-sourced attr DOES survive
    when it's in the Tier C required_vns set (AttrSequence-Required, not
    curated-Recommended, not data-table-resolvable) — Tier C is exactly
    the mechanism for defaulted-but-genuinely-editable Mandatory fields
    like Solution Type."""
    eng = CpqEngine()
    attrs = [_attr(1, "solutionTypeDevices_astro", "Solution Type")]
    display_filled = {"solutionTypeDevices_astro": "RadioCentral with CPS"}
    rule_governed_ids = {1}
    sources = {"solutionTypeDevices_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources,
        required_vns=frozenset({"solutionTypeDevices_astro"}),
    )
    assert [t[0] for t in triples] == ["solutionTypeDevices_astro"]


def test_summary_includes_a_real_user_answer_even_if_rule_governed():
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    display_filled = {"batteryType_astro": "Extended"}
    rule_governed_ids = {1}
    sources = {"batteryType_astro": "user"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert [t[0] for t in triples] == ["batteryType_astro"]


def test_summary_excludes_optional_tier_fill():
    eng = CpqEngine()
    attrs = [_attr(1, "spSurveillancePackagesType_astro", "Surveillance Package")]
    display_filled = {"spSurveillancePackagesType_astro": "Impress 3-Wire Surveillance Kit - Beige"}
    rule_governed_ids = {1}
    sources = {"spSurveillancePackagesType_astro": "optional"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_includes_confirmed_product_switch_anchor():
    # Real transcript (confirmed live): productSelectionProduct_all is
    # seeded with filled_source="product_anchor" right after a CONFIRMED
    # product switch ("yes" to "Switch to aSTRO25_bom?") — a genuine
    # decision, just under its own distinct source tag rather than "user".
    # Also a Tier A structural anchor regardless of source, so this
    # survives via _is_mandatory_input_attr's Tier A check.
    eng = CpqEngine()
    attrs = [_attr(1, "productSelectionProduct_all", "Product")]
    display_filled = {"productSelectionProduct_all": "APX NEXT Enhanced"}
    rule_governed_ids = {1}
    sources = {"productSelectionProduct_all": "product_anchor"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert [t[0] for t in triples] == ["productSelectionProduct_all"]


def test_summary_excludes_administrative_rule_sourced_attr():
    eng = CpqEngine()
    attrs = [_attr(1, "modelSelectionOrderType_astro", "Order Type")]
    display_filled = {"modelSelectionOrderType_astro": "New KVL 4000"}
    rule_governed_ids = {1}
    sources = {"modelSelectionOrderType_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_excludes_curated_recommended_only_attr_even_via_tier_c():
    """2026-08-19 update: antennasType_astro is one of the confirmed
    Recommended-Configuration-only attrs (_RECOMMENDED_CONFIG_ONLY_VNS) —
    it must stay excluded from the summary even if it were (hypothetically)
    passed in required_vns, since mandatory_tier_c_vns itself would never
    include it. Directly exercising _is_mandatory_input_attr's own Tier C
    exclusion here, independent of how required_vns gets computed."""
    eng = CpqEngine()
    attrs = [_attr(1, "antennasType_astro", "Antenna Type")]
    display_filled = {"antennasType_astro": "Whip All Band VHF, UHF, 7/800 MHz 20 cm (Standard)"}
    rule_governed_ids = {1}
    sources = {"antennasType_astro": "rule"}

    # Even if antennasType_astro somehow ended up in required_vns, it is
    # excluded elsewhere (mandatory_tier_c_vns filters by
    # _RECOMMENDED_CONFIG_ONLY_VNS) — this test only confirms the
    # baseline (no required_vns) stays excluded, which it already does
    # via the same source="rule" reasoning as the sibling tests above.
    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_falls_back_to_tier_a_b_only_when_sources_not_supplied():
    """2026-08-19 update: omitting `sources` entirely means no attribute
    can be confirmed as an active per-turn decision — only Tier A
    structural anchors survive without it. A non-anchor attr like Battery
    Type, with no source information at all, is no longer assumed
    Mandatory just because some rule targets it."""
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    display_filled = {"batteryType_astro": "Standard"}
    rule_governed_ids = {1}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=None)
    assert triples == []


def test_categorized_summary_groups_renames_catchall_to_mandatory_in_narrowed_scope():
    """PR #223, N1 follow-up: a triple that would land in the old catch-all
    category (its variable_name matches none of Product Name/Service
    Plan/Quantity & Duration's fragments) must be bucketed under
    "Mandatory User Input", not "Associated Options", once the narrowed
    "sales rep talking points" scope (rule_governed_ids supplied) has
    already restricted the whole item list to exactly the Mandatory set
    (`_is_mandatory_input_attr`, Tier A/B/C — PR #222). The rename is a
    relabel, not a re-check: `batteryType_astro` here is only source=
    "user" (Tier B), not independently Tier A/C, and still gets renamed
    because everything reaching this bucket in this scope is mandatory by
    construction.

    `render_filled_summary` must render it as a full bullet — the old
    catch-all's "one vague, intentionally-partial line" treatment no
    longer applies once the category is renamed."""
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    display_filled = {"batteryType_astro": "Extended"}
    rule_governed_ids = {1}
    sources = {"batteryType_astro": "user"}

    groups = eng.categorized_summary_groups(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert groups == [("Mandatory User Input", [("Battery Type", "Extended")])]

    summary = eng.render_filled_summary(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert summary == (
        "**Key decisions:**\n"
        "\n**Mandatory User Input:**\n"
        "- **Battery Type** → Extended"
    )


def test_categorized_summary_groups_keeps_associated_options_in_full_dump_scope():
    """Sibling to the rename test above: the SAME catch-all attr, under the
    full-detail-dump scope (rule_governed_ids=None, which is never
    narrowed to mandatory-only), must keep the original "Associated
    Options" name and its collapsed one-line rendering — completely
    unaffected by the narrowed-scope rename in `categorized_summary_
    groups`/`render_filled_summary`."""
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    display_filled = {"batteryType_astro": "Extended"}

    groups = eng.categorized_summary_groups(display_filled, attrs, rule_governed_ids=None)
    assert groups == [("Associated Options", [("Battery Type", "Extended")])]

    summary = eng.render_filled_summary(display_filled, attrs, rule_governed_ids=None)
    assert summary == (
        "**Configured so far:**\n"
        "\n**Associated Options:**\n"
        "Battery Type: Extended."
    )
