"""docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md

auto_fill's multi-select branch treated "here is the current menu of
constraint-allowed choices" as "auto-select every one of them", for any
active constraint however many options it left standing. Real incident:
"Constrain Additional feature Type" (condition: any product selected --
true for virtually every order) narrows a real attribute to 9 of 11
options; that 9-item list is a MENU definition, not a recommendation to
select all 9. auto_fill force-selected all 9 (including "ICE KIT"), which
silently triggered an unrelated constraint that collapsed a real question
(Package Type) to zero valid options.

Fix 1: require len(valid_opts) == 1 for the multi-select auto-select-via-
constraint path, exactly mirroring the single-select safeguard directly
above it in the same function.

Fix 2 (superseded by an explicit product decision below): an interim fix
made an ambiguous (2+ remaining options), constrained multi-select fall
through to `pending` (asked) instead of a false "confirmed empty" --
because _filled_by_rule_id treats an explicit [] as a real, known-empty
value, which let a sibling rule keyed on "does NOT contain value X"
(operator "8", disjoint-from) fire on it as if the customer had confirmed
nothing. Live-verifying that interim fix surfaced a real new question
("Feature Type") the product owner did not want asked. Explicit decision
(HITL-confirmed): prefer the XML default_value when it's still a
currently-valid option; otherwise default to empty and do not ask --
accepting the disjoint-from risk Fix 2 had closed, as a deliberate
trade for fewer conversational questions (see engine.py's
auto_fill docstring and the plan doc's "explicit product decision"
addendum for the full rationale and the accepted risk).

Fix 4 (further HITL-confirmed refinement): "empty" was still not what the
product wanted for a GENUINELY unconstrained optional multi-select (no
active constraint rule ever targeted it at all this turn) -- live example
relatedServicesType_astro ("Service Type", zero active constraints, no
default_value). For that specific case, first real menu option by
catalog order is now picked instead of empty, mirroring the existing
single-select convention. The CONSTRAINED-but-ambiguous case (Feature
Type-like: a real rule narrowed the menu to 2+ options, just not exactly
one) explicitly keeps Fix 3's default-value-or-empty behavior --
picking an arbitrary one of several rule-narrowed options would be
exactly the guessing risk Fix 1 exists to prevent, just applied to a
smaller set.
"""
from __future__ import annotations

import pytest

from aryx.cpq import data_table_resolver
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption


@pytest.fixture(autouse=True)
def _clear_tables_cache():
    data_table_resolver._clear_tables_cache()
    yield
    data_table_resolver._clear_tables_cache()


class _FakeRdb:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def list_ontology_types(self, workspace_id):
        return list(self._tables.keys())

    def fetch_entities_by_type(self, workspace_id, type_suffix, catalog_prefix=""):
        rows = self._tables.get(type_suffix, [])
        return [(i, r) for i, r in enumerate(rows, start=1)]

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        rows = self._tables.get(ontology_type, [])
        return [(i, r) for i, r in enumerate(rows, start=1)]


def _patch_rdb(monkeypatch, tables: dict[str, list[dict]]) -> None:
    monkeypatch.setattr(data_table_resolver, "get_cpq_rdb", lambda: _FakeRdb(tables))


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_multiselect_with_several_constrained_options_and_no_default_defaults_to_empty():
    """Replays the real "additionalSystemEnhancementFeatureType_astro"
    shape: a near-universal constraint narrows 11 real options down to 9,
    and the attribute has no default_value in the raw XML -- must NOT
    auto-select all 9, and (per the explicit product decision) must
    default to empty rather than asking."""
    attr = ConfigAttr(
        entity_id=1, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "DELETE NARROWBANDING-WAIVER REQUIRED",
            "ICE KIT", "OPTIONAL EMERGENCY TONE", "SEQUENTIAL SERIAL NUMBER",
            "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
            "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
        ),
    )
    constrained_opts = {1: [
        "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
        "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
        "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
    ]}  # 8 of 10 remain -- multiple options, not a deterministic single choice

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={1}, rule_governed_ids={1}, already_filled_multi=multi,
    )

    assert multi.get("additionalSystemEnhancementFeatureType_astro") == [], (
        "no matching default_value and several remaining options -- must "
        "not auto-select all of them, and per the explicit product "
        "decision must default to empty rather than asking"
    )


def test_multiselect_with_several_constrained_options_and_a_default_uses_the_default():
    """A constrained, ambiguous multi-select whose XML default_value IS
    still one of the currently-valid options must auto-select just that
    default -- not all remaining options, not empty."""
    attr = ConfigAttr(
        entity_id=5, variable_name="someOptionalMulti_astro", display_label="Some Optional Multi",
        required=False, default_value="OPTION B", select_type="multi",
        options=_menu("OPTION A", "OPTION B", "OPTION C", "OPTION D"),
    )
    constrained_opts = {5: ["OPTION A", "OPTION B", "OPTION C"]}  # 3 remain, default among them

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={5}, rule_governed_ids={5}, already_filled_multi=multi,
    )

    assert multi.get("someOptionalMulti_astro") == ["OPTION B"]


def test_multiselect_default_value_excluded_by_constraint_falls_back_to_empty():
    """If the constraint has excluded the raw default_value from the
    currently-valid set, it must never be selected anyway (that would
    violate the active constraint) -- falls back to empty instead."""
    attr = ConfigAttr(
        entity_id=6, variable_name="anotherOptionalMulti_astro", display_label="Another Optional Multi",
        required=False, default_value="OPTION Z", select_type="multi",
        options=_menu("OPTION X", "OPTION Y", "OPTION Z"),
    )
    constrained_opts = {6: ["OPTION X", "OPTION Y"]}  # OPTION Z (the default) is excluded

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={6}, rule_governed_ids={6}, already_filled_multi=multi,
    )

    assert multi.get("anotherOptionalMulti_astro") == []


def test_multiselect_with_no_menu_options_and_a_default_value_does_not_crash():
    """Regression (live incident, "APX NEXT All Band" order): a multi-
    select attr reaching the ambiguous-default fallback with an EMPTY
    options list never enters the sibling `if not value and attr.options:`
    block above, so `valid_opts` from that block is never assigned this
    iteration. This attr's own default_value is valid on its own terms
    but an active constraint excludes it (the generic default_value step
    a few lines above this one correctly declines to auto-lock it in),
    so `value` stays empty and falls all the way through to this branch
    -- where referencing `valid_opts` directly threw UnboundLocalError in
    production. Must default to empty without crashing."""
    attr = ConfigAttr(
        entity_id=7, variable_name="noOptionsMulti_astro", display_label="No Options Multi",
        required=False, default_value="SOME DEFAULT", select_type="multi",
        options=[],
    )
    constrained_opts = {7: ["SOMETHING ELSE ENTIRELY"]}  # excludes the default_value
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={7}, rule_governed_ids={7}, already_filled_multi=multi,
    )
    assert multi.get("noOptionsMulti_astro") == []


def test_multiselect_constrained_to_exactly_one_option_is_still_auto_selected():
    """Regression: narrowing to exactly ONE remaining option is exactly as
    unambiguous for multi-select as it already is for single-select --
    must remain auto-filled, unchanged from before this fix."""
    attr = ConfigAttr(
        entity_id=2, variable_name="packageTypeBundles_astro", display_label="Software Bundles",
        required=False, default_value="", select_type="multi",
        options=_menu("CORE BUNDLE", "SECURITY BUNDLE", "TACTICAL BUNDLE"),
    )
    constrained_opts = {2: ["CORE BUNDLE"]}

    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={2}, rule_governed_ids={2}, already_filled_multi=multi,
    )

    assert multi.get("packageTypeBundles_astro") == ["CORE BUNDLE"]


def test_multiselect_first_available_guess_is_reopened_once_a_real_constraint_appears():
    """Live incident: evaluate_rules_loop's fixed-point iteration calls
    auto_fill repeatedly as state settles. On an EARLY pass (before
    productSelectionProduct_all itself was filled),
    additionalSystemEnhancementFeatureType_astro was genuinely
    unconstrained -- Fix 4 correctly picked its first option ("DISABLE
    CLOUD SERVICES"). On the NEXT pass, Product resolved and activated
    this attr's real 9-of-11 constraint -- but the guess, still
    technically a member of the new allowed set, got silently kept
    instead of re-deriving Fix 3's real default-or-empty answer for the
    now-ambiguous, constrained case. Simulates both passes directly
    against the same mutable filled_multi/filled_source dicts, exactly
    as evaluate_rules_loop does."""
    attr = ConfigAttr(
        entity_id=1, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "DELETE NARROWBANDING-WAIVER REQUIRED",
            "ICE KIT", "OPTIONAL EMERGENCY TONE", "SEQUENTIAL SERIAL NUMBER",
            "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
            "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
        ),
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    source: dict[str, str] = {}

    # Pass 1: genuinely unconstrained (Product not yet resolved).
    eng.auto_fill(
        [attr], hints={}, constrained_opts=None,
        governed_ids={1}, rule_governed_ids={1},
        already_filled_multi=multi, filled_source=source,
    )
    assert multi.get("additionalSystemEnhancementFeatureType_astro") == ["DISABLE CLOUD SERVICES"]
    assert source.get("additionalSystemEnhancementFeatureType_astro") == "default_first_available"

    # Pass 2: Product now resolved, real constraint narrows to 9 of 10 --
    # "DISABLE CLOUD SERVICES" is still technically a member of the new
    # allowed set, but must NOT be blindly kept; must re-derive to empty
    # (no default_value, several remaining options -- Fix 3's own rule).
    constrained_opts = {1: [
        "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
        "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
        "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
        "DELETE NARROWBANDING-WAIVER REQUIRED",
    ]}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={1}, rule_governed_ids={1},
        already_filled_multi=multi, filled_source=source,
    )
    assert multi.get("additionalSystemEnhancementFeatureType_astro") == [], (
        "a first-available guess from an earlier, unconstrained pass must "
        "be re-opened once a real constraint activates -- not blindly kept "
        "just because it happens to still be technically valid"
    )


def test_multiselect_with_no_active_constraint_and_no_default_picks_first_option():
    """Fix 4 (live incident: "APX NEXT All Band" order, relatedServicesType_
    astro "Service Type" -- zero active constraints, no default_value, kept
    getting silently re-asked despite being defaulted). A genuinely
    unconstrained optional multi-select with no default_value now picks the
    catalog's first real menu option instead of staying empty."""
    attr = ConfigAttr(
        entity_id=3, variable_name="carrierSelectionMultiSelect_astro", display_label="Carrier Selection",
        required=False, default_value="", select_type="multi",
        options=_menu("ATT/FIRSTNET", "VERIZON", "T MOBILE"),
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=None,
        governed_ids={3}, rule_governed_ids={3}, already_filled_multi=multi,
    )
    assert multi.get("carrierSelectionMultiSelect_astro") == ["ATT/FIRSTNET"]


def test_multiselect_with_no_active_constraint_and_a_default_uses_the_default_not_first():
    """A genuinely unconstrained multi-select with a real default_value
    still prefers that default over blindly picking the first menu
    option -- default_value always wins when it's actually available."""
    attr = ConfigAttr(
        entity_id=8, variable_name="someUnconstrainedMulti_astro", display_label="Some Unconstrained Multi",
        required=False, default_value="OPTION TWO", select_type="multi",
        options=_menu("OPTION ONE", "OPTION TWO", "OPTION THREE"),
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=None,
        governed_ids={8}, rule_governed_ids={8}, already_filled_multi=multi,
    )
    assert multi.get("someUnconstrainedMulti_astro") == ["OPTION TWO"]


def test_multiselect_trivial_single_real_option_total_is_auto_selected():
    """Regression: an attribute with only ONE real option in the whole
    catalog (constrained set == the full option set) is still safely
    auto-filled -- there's no ambiguity when there's only one thing to
    ever pick."""
    attr = ConfigAttr(
        entity_id=4, variable_name="provisioningAssistance_astro", display_label="Provisioning Assistance",
        required=False, default_value="", select_type="multi",
        options=_menu("YES"),
    )
    constrained_opts = {4: ["YES"]}
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={4}, rule_governed_ids={4}, already_filled_multi=multi,
    )
    assert multi.get("provisioningAssistance_astro") == ["YES"]


def test_confirmed_empty_multiselect_can_satisfy_a_sibling_disjoint_from_rule():
    """Documents the KNOWN, ACCEPTED risk of the explicit product decision
    above (not a bug to fix): once an ambiguous multi-select defaults to
    [], _filled_by_rule_id reports that as a real, known-empty value, so a
    sibling ConstraintRule keyed on "does NOT contain value X" (operator
    "8", disjoint-from) can fire on it exactly as if the customer had
    confirmed nothing. This is the same mechanism that collapsed Package
    Type live via a rule unrelated to the ICE-KIT one Fix 1 addressed
    (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md's
    "Known remaining issue" section) -- kept here as a regression/
    documentation test of the mechanism itself, at the
    apply_constraint_rules level, independent of what auto_fill currently
    chooses to do with it."""
    feature_attr = ConfigAttr(
        entity_id=10, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
            "FRONT PANEL PROGRAMMING & CLONING", "FRONT PANEL PROGRAMMING & CLONING FED",
            "PROGRAMMING OVER P25", "PSU CONV SCAN", "WEB BROWSER ENABLEMENT",
            "SEQUENTIAL SERIAL NUMBER", "DELETE NARROWBANDING-WAIVER REQUIRED",
        ),
    )
    package_type_attr = ConfigAttr(
        entity_id=11, variable_name="packingPackageType_astro", display_label="Package Type",
        required=False, default_value="", select_type="single",
        options=_menu("BULK XE", "SINGLE XE", "SINGLE PACK CLAMSHELL"),
    )
    product_attr = ConfigAttr(
        entity_id=12, variable_name="productSelectionProduct_all", display_label="Product",
        required=True, default_value="", select_type="single",
        options=_menu("APX NEXT XE SINGLE BAND"),
    )
    attrs = [feature_attr, package_type_attr, product_attr]
    filled = {"productSelectionProduct_all": "APX NEXT XE SINGLE BAND"}

    # Mirrors the real "Hide Single Pack Calmshell when...is not selected
    # as feature type" rule: fires when the feature-type attr does NOT
    # contain ICE KIT, restricting Package Type to a value real product-
    # based rules never allow for this product -- an empty intersection
    # results the moment this rule fires on a false "confirmed empty".
    disjoint_from_rule = ConstraintRule(
        rule_name="Hide Single Pack Calmshell when not ICE KIT",
        condition_attr_id=feature_attr.entity_id, condition_value="ICE KIT",
        condition_operator="8", target_attr_id=package_type_attr.entity_id,
        allowed_values=["SINGLE PACK CLAMSHELL"],
        conditions=[(feature_attr.entity_id, "ICE KIT", "8")],
    )
    # Mirrors the real "Constrain APX NEXT XE & XN" rule -- allows
    # BULK XE/SINGLE XE once this product line is selected.
    product_based_rule = ConstraintRule(
        rule_name="Constrain APX NEXT XE & XN",
        condition_attr_id=product_attr.entity_id,
        condition_value="APX NEXT XE SINGLE BAND", condition_operator="4",
        target_attr_id=package_type_attr.entity_id,
        allowed_values=["BULK XE", "SINGLE XE"],
    )

    eng = CpqEngine()

    # A confirmed/defaulted-empty feature attr satisfies disjoint-from and
    # collapses the intersection to empty -- the accepted, documented risk.
    constrained_confirmed_empty = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={"additionalSystemEnhancementFeatureType_astro": []},
    )
    assert constrained_confirmed_empty.get(package_type_attr.entity_id) == []

    # A genuinely unresolved (absent from filled_multi entirely) attr must
    # NOT satisfy disjoint-from -- Package Type keeps its real allowed set.
    # This is what auto_fill would leave behind for a REQUIRED multi-select
    # (never defaulted, always falls through to pending) -- contrast with
    # the non-required case above, which auto_fill now defaults to [].
    constrained_unresolved = eng.apply_constraint_rules(
        attrs, [disjoint_from_rule, product_based_rule], filled=filled,
        filled_multi={},
    )
    assert constrained_unresolved.get(package_type_attr.entity_id) == ["BULK XE", "SINGLE XE"]


def test_unconstrained_governed_multiselect_blind_picks_even_with_layout_loaded():
    """docs/CPQ_MULTISELECT_GOVERNED_NO_MATCH_ASK_PLAN_2026_08_10.md.

    Live bug: carrierSelectionMultiSelect_astro (real attrSequence Data
    Table coverage, 6 real carrier options, no active constraint, no
    recommendation fires, no default_value) was missing entirely from a
    real BOM payload -- not filled, not asked. Root cause: `elif
    display_order is not None: pass` intercepted the genuinely-unconstrained
    case BEFORE it could ever reach the existing, already-correct
    `is_unconstrained and candidate_opts` blind-pick a few lines below,
    purely because a layout map happened to be loaded (the normal,
    always-true production case). Every existing test in this file omits
    display_order entirely, which is exactly why this gap was invisible
    until a real container replay surfaced it."""
    attr = ConfigAttr(
        entity_id=20, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier Selection", required=False, default_value="",
        select_type="multi",
        options=_menu("ATT/FIRSTNET", "T MOBILE", "VERIZON"),
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    source: dict[str, str] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=None,
        governed_ids={20}, rule_governed_ids={20},
        already_filled_multi=multi, filled_source=source,
        display_order={"carrierSelectionMultiSelect_astro": 5},
    )
    assert multi.get("carrierSelectionMultiSelect_astro") == ["ATT/FIRSTNET"]
    assert source.get("carrierSelectionMultiSelect_astro") == "default_first_available"


def test_constrained_ambiguous_multiselect_still_stays_empty_with_layout_loaded():
    """Regression lock: the narrowed `pass` condition must not accidentally
    let the CONSTRAINED-but-ambiguous case (a real rule narrowed the menu
    to 2+ options, just not exactly one) fall through to a blind pick.
    Confirmed identical to this exact scenario's pre-fix behavior (verified
    via `git stash` comparison): with a layout map loaded, this case was
    already left absent from filled_multi entirely (not explicitly `[]` --
    that only happens without a layout map, via a different, later `else`
    this scenario never reaches either way) -- this fix must not touch that
    at all, only the genuinely-unconstrained shape below it."""
    attr = ConfigAttr(
        entity_id=21, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "DELETE NARROWBANDING-WAIVER REQUIRED",
            "ICE KIT", "OPTIONAL EMERGENCY TONE", "SEQUENTIAL SERIAL NUMBER",
        ),
    )
    constrained_opts = {21: [
        "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
    ]}  # 3 of 5 remain -- ambiguous, not exactly one
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={21}, rule_governed_ids={21}, already_filled_multi=multi,
        display_order={"additionalSystemEnhancementFeatureType_astro": 5},
    )
    assert multi.get("additionalSystemEnhancementFeatureType_astro") is None


def test_blind_pick_uses_the_real_narrowed_whitelist_not_raw_catalog_order(monkeypatch):
    """docs/CPQ_MULTISELECT_BLIND_PICK_RESPECTS_WHITELIST_PLAN_2026_08_10.md.

    Live bug: carrierSelectionMultiSelect_astro's blind-pick used the raw
    catalog menu order, which can include a real, data-proven-ILLEGAL
    option for the current context. Replays that exact shape: the raw
    catalog's FIRST option ("BELL CANADA") is real-data-illegal for this
    destination country; the real Data Table narrows the legal set to 2
    other options. The narrowed set's first member must be picked, not the
    raw catalog's first member."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "carrierSelectionMultiSelect_astro", "val1": "BELL CANADA",
             "attr2": "ultimateDestinationCountry", "val2": "CA"},
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "carrierSelectionMultiSelect_astro", "val1": "ATT/FIRSTNET",
             "attr2": "ultimateDestinationCountry", "val2": "US"},
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "carrierSelectionMultiSelect_astro", "val1": "T MOBILE",
             "attr2": "ultimateDestinationCountry", "val2": "US"},
        ],
    })
    attr = ConfigAttr(
        entity_id=30, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier", required=False, default_value="",
        select_type="multi",
        options=[
            MenuOption(item_value="BELL CANADA", display_name="Bell Canada", order=1),
            MenuOption(item_value="ATT/FIRSTNET", display_name="ATT/FirstNet", order=2),
            MenuOption(item_value="T MOBILE", display_name="T-Mobile", order=3),
        ],
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    source: dict[str, str] = {}
    eng.auto_fill(
        [attr], hints={},
        already_filled={
            "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
            "productSelectionProduct_all": "APX NEXT MULTI",
            "ultimateDestinationCountry": "US",
        },
        governed_ids={30}, rule_governed_ids={30},
        already_filled_multi=multi, filled_source=source,
        display_order={"carrierSelectionMultiSelect_astro": 5},
        workspace_id=7,
    )
    assert multi.get("carrierSelectionMultiSelect_astro") == ["ATT/FIRSTNET"], (
        "must pick from the real narrowed legal set (ATT/FIRSTNET, T MOBILE), "
        "never BELL CANADA -- real data proves it illegal for this US order, "
        "even though it's the raw catalog's first-listed option"
    )
    assert source.get("carrierSelectionMultiSelect_astro") == "default_first_available"


def test_blind_pick_falls_to_empty_when_whitelist_confirms_zero_legal_values(monkeypatch):
    """Real Data Table coverage exists for this attr/context but every row's
    condition fails to match -- a confirmed, real "nothing is legal right
    now" answer, not something to guess past."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "carrierSelectionMultiSelect_astro", "val1": "BELL CANADA",
             "attr2": "ultimateDestinationCountry", "val2": "CA"},
        ],
    })
    attr = ConfigAttr(
        entity_id=31, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier", required=False, default_value="",
        select_type="multi",
        options=[
            MenuOption(item_value="BELL CANADA", display_name="Bell Canada", order=1),
            MenuOption(item_value="ATT/FIRSTNET", display_name="ATT/FirstNet", order=2),
        ],
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={},
        already_filled={
            "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
            "productSelectionProduct_all": "APX NEXT MULTI",
            "ultimateDestinationCountry": "US",  # doesn't match the one row's "CA"
        },
        governed_ids={31}, rule_governed_ids={31}, already_filled_multi=multi,
        display_order={"carrierSelectionMultiSelect_astro": 5},
        workspace_id=7,
    )
    assert multi.get("carrierSelectionMultiSelect_astro") == []


def test_blind_pick_unchanged_when_no_table_coverage_at_all(monkeypatch):
    """No ingested Data Table row at all for this attr -- raw catalog-order
    pick, exactly today's pre-whitelist-narrowing behavior. Regression lock
    for the earlier CPQ_MULTISELECT_GOVERNED_NO_MATCH_ASK_PLAN fix."""
    _patch_rdb(monkeypatch, {"WhitelistTest": []})
    attr = ConfigAttr(
        entity_id=32, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier", required=False, default_value="",
        select_type="multi",
        options=[
            MenuOption(item_value="VERIZON", display_name="Verizon", order=1),
            MenuOption(item_value="ATT/FIRSTNET", display_name="ATT/FirstNet", order=2),
        ],
    )
    eng = CpqEngine()
    multi: dict[str, list[str]] = {}
    eng.auto_fill(
        [attr], hints={},
        already_filled={
            "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
            "productSelectionProduct_all": "APX NEXT MULTI",
        },
        governed_ids={32}, rule_governed_ids={32}, already_filled_multi=multi,
        display_order={"carrierSelectionMultiSelect_astro": 5},
        workspace_id=7,
    )
    assert multi.get("carrierSelectionMultiSelect_astro") == ["VERIZON"]
