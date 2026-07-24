"""Regression coverage: "Associated Options" narrows to attrs a rule
ACTUALLY reasoned about this turn (filled_source in a genuine-decision
set), not merely attrs targeted by some rule anywhere in the catalog.

rule_governed_ids() is static — "this attr is the target of at least one
loaded rule" — regardless of whether that rule's condition held THIS
turn. As more real rules got correctly wired up this session (array-set
grouping, the recommendation-priority fix, duplicate-attr dedup), that
static set grew, silently widening the summary past the intended "key
attributes actually decided" scope (product decision, confirmed via user
feedback). filled_source is the per-turn signal for whether a rule
genuinely fired ("rule"/"country_derived") or the user genuinely chose
something ("user"/"hint"/"cascade"/"cascade-dependent"), as opposed to a
bland "default"/"optional"/"auto" fill nobody reasoned about this turn.
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
    rule_governed_ids = {1}  # some rule in the catalog targets this attr
    sources = {"packages_astro": "default"}  # but nothing reasoned about it THIS turn

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_includes_rule_governed_attr_whose_rule_actually_fired():
    eng = CpqEngine()
    attrs = [_attr(1, "solutionTypeDevices_astro", "Solution Type")]
    display_filled = {"solutionTypeDevices_astro": "RadioCentral with CPS"}
    rule_governed_ids = {1}
    sources = {"solutionTypeDevices_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
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
    # Omitting it from the active-sources set meant "Product" was missing
    # from the summary on exactly the turn it was decided, only
    # reappearing later once a cascade happened to re-tag it "rule".
    eng = CpqEngine()
    attrs = [_attr(1, "productSelectionProduct_all", "Product")]
    display_filled = {"productSelectionProduct_all": "APX NEXT Enhanced"}
    rule_governed_ids = {1}
    sources = {"productSelectionProduct_all": "product_anchor"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert [t[0] for t in triples] == ["productSelectionProduct_all"]


def test_summary_excludes_administrative_associated_options_attr():
    # Curated business-relevance narrowing (product decision, follow-up
    # after "narrow to rules that actually fired" still left ~24 largely
    # administrative items in a real APX NEXT quote): a rule-fired attr in
    # the Associated Options fallback category, but not a curated
    # business-relevant fragment, is excluded — sales reps don't need
    # "Order Type" or "Software Release" read out loud.
    eng = CpqEngine()
    attrs = [_attr(1, "modelSelectionOrderType_astro", "Order Type")]
    display_filled = {"modelSelectionOrderType_astro": "New KVL 4000"}
    rule_governed_ids = {1}
    sources = {"modelSelectionOrderType_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert triples == []


def test_summary_includes_business_relevant_associated_options_attr():
    eng = CpqEngine()
    attrs = [_attr(1, "antennasType_astro", "Antenna Type")]
    display_filled = {"antennasType_astro": "Whip All Band VHF, UHF, 7/800 MHz 20 cm (Standard)"}
    rule_governed_ids = {1}
    sources = {"antennasType_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert [t[0] for t in triples] == ["antennasType_astro"]


def test_summary_curated_filter_does_not_apply_to_service_plan_category():
    # The curated fragment filter only narrows the Associated Options
    # fallback — Service Plan (matched via the "solutiontype" fragment)
    # must survive even though "solutiontype" isn't itself in the curated
    # Associated Options fragment set.
    eng = CpqEngine()
    attrs = [_attr(1, "solutionTypeDevices_astro", "Solution Type")]
    display_filled = {"solutionTypeDevices_astro": "RadioCentral with CPS"}
    rule_governed_ids = {1}
    sources = {"solutionTypeDevices_astro": "rule"}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources)
    assert [t[0] for t in triples] == ["solutionTypeDevices_astro"]


def test_summary_falls_back_to_static_scope_when_sources_not_supplied():
    # Backward-compat: callers that don't pass `sources` at all (rare, but
    # the parameter is optional) must keep the pre-existing static-scope
    # behavior, not suddenly exclude everything.
    eng = CpqEngine()
    attrs = [_attr(1, "batteryType_astro", "Battery Type")]
    display_filled = {"batteryType_astro": "Standard"}
    rule_governed_ids = {1}

    triples = eng._filled_summary_triples(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=None)
    assert [t[0] for t in triples] == ["batteryType_astro"]
