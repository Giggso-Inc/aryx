"""Tests for data_table_resolver.py, which reads real Oracle CPQ Data Table
data (`whitelist`/`attrSequence`-shaped rows) from Aryx's ingested entity
store (aryx_entity via get_cpq_rdb()) -- never from a bundled/hardcoded CSV
file. A fake rdb (monkeypatched onto `get_cpq_rdb`) stands in for Postgres,
same pattern as tests/test_cpq_rdb_attr_set_assoc.py.

Every real-data assertion here (the APX NEXT ones) reproduces a fact
independently confirmed earlier in docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_
GAP_PROOF_2026_08_07.md §11 (a real Oracle CPQ admin trace page's own
ConstraintMasterString/hiddenMasterStringForAstroPortable values, and the
live Pipeline Viewer capture from §8) -- not fixture data invented for this
test file.
"""
from __future__ import annotations

import pytest

from aryx.cpq import data_table_resolver
from aryx.cpq.data_table_resolver import resolve_product_cpq_model_family


@pytest.fixture(autouse=True)
def _clear_tables_cache():
    """_load_all_tables now has a module-level, process-lifetime (short-TTL)
    cache keyed by (workspace_id, catalog_prefix) -- clear it between tests
    so one test's fake/monkeypatched rows can never leak into another via
    that shared cache (many tests here reuse workspace_id=1/7)."""
    data_table_resolver._clear_tables_cache()
    yield
    data_table_resolver._clear_tables_cache()


class _FakeRdb:
    """ontology_type -> list[dict] of ingested rows, exactly what a real
    CSV upload produces (JSONB attributes keyed by the CSV's own headers)."""

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


# --- Real APX NEXT data, as ingested from whitelist_apxnext.csv /
# attr_sequence_apxnext.csv would have been -- same rows, just handed to the
# fake rdb directly instead of read from a bundled file.

_WIRELESS_CARRIER_ROWS = [
    {"CPQModel": "APXNEXT_BOM", "BaseModel": "H55TGT9PW8AN",
     "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET",
     "attr2": "ultimateDestinationCountry", "val2": "US"},
    {"CPQModel": "APXNEXT_BOM", "BaseModel": "H55TGT9PW8AN",
     "attr1": "wirelessCarrier_astro", "val1": "VERIZON",
     "attr2": "ultimateDestinationCountry", "val2": "US"},
    {"CPQModel": "APXNEXT_BOM", "BaseModel": "ALL",
     "attr1": "wirelessCarrier_astro", "val1": "LTE CAPABILITY NO SERVICE"},
    {"CPQModel": "APXNEXT_BOM", "BaseModel": "ALL",
     "attr1": "wirelessCarrier_astro", "val1": "LTE CAPABILITY NO SERVICE",
     "attr2": "ultimateDestinationCountry", "val2": "GU",
     "attr3": "customerType", "val3": "FEDERAL"},
]

_CARRIER_SELECTION_ROWS = [
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "ATT/FIRSTNET",
     "attr2": "ultimateDestinationCountry", "val2": "US",
     "attr3": "aTAKEnabledPackage_astro", "val3": "NO"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "T MOBILE",
     "attr2": "ultimateDestinationCountry", "val2": "US",
     "attr3": "aTAKEnabledPackage_astro", "val3": "NO"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "VERIZON",
     "attr2": "ultimateDestinationCountry", "val2": "US",
     "attr3": "aTAKEnabledPackage_astro", "val3": "NO"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "BELL CANADA(PROVIDED BY MOTOROLA)",
     "attr2": "ultimateDestinationCountry", "val2": "CA",
     "attr3": "aTAKEnabledPackage_astro", "val3": "NO"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "T MOBILE AND T SATELLITE",
     "attr2": "ultimateDestinationCountry", "val2": "US",
     "attr3": "aTAKEnabledPackage_astro", "val3": "NO",
     "attr4": "applicationServicesSelection_astro", "val4": "STANDALONE APP SERVICES"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "attr1": "carrierSelectionMultiSelect_astro", "val1": "LTE CAPABILITY NO SERVICE"},
]

_ATTR_SEQUENCE_ROWS = [
    {"CPQModel": "APXNEXT_BOM", "BaseModel": "H55TGT9PW8AN",
     "AttrName": "wirelessCarrier_astro", "Seq": "315", "optionOrReqFlag": "R"},
    {"CPQModel": "APXNEXTENHANCED", "BaseModel": "H55TGT9PW8BN",
     "AttrName": "carrierSelectionMultiSelect_astro", "Seq": "342", "optionOrReqFlag": "R"},
]

_TABLES = {
    "WhitelistApxnext": _WIRELESS_CARRIER_ROWS + _CARRIER_SELECTION_ROWS,
    "AttrSequenceApxnext": _ATTR_SEQUENCE_ROWS,
}


def test_wireless_carrier_for_H55TGT9PW8AN_us_matches_pipeline_viewer_capture(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXT_BOM", "H55TGT9PW8AN", "wirelessCarrier_astro",
        {"ultimateDestinationCountry": "US"}, workspace_id=1,
    )
    assert result == ["ATT/FIRSTNET", "LTE CAPABILITY NO SERVICE", "VERIZON"]


def test_wireless_carrier_gu_federal_row_excluded_for_a_us_customer(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXT_BOM", "H55TGT9PW8AN", "wirelessCarrier_astro",
        {"ultimateDestinationCountry": "US"}, workspace_id=1,
    )
    assert len(result) == 3  # the GU+FEDERAL-conditioned row must not leak an extra value in


def test_carrier_selection_multiselect_for_H55TGT9PW8BN_apxnextenhanced(monkeypatch):
    """Real 6-value set from the live trace page's ConstraintMasterString
    for APX NEXT ENHANCED / H55TGT9PW8BN, cross-checked in the session."""
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXTENHANCED", "H55TGT9PW8BN", "carrierSelectionMultiSelect_astro",
        {"ultimateDestinationCountry": "US", "aTAKEnabledPackage_astro": "NO"},
        workspace_id=1,
    )
    assert result == [
        "ATT/FIRSTNET", "LTE CAPABILITY NO SERVICE", "T MOBILE", "VERIZON",
    ]
    assert "T MOBILE AND T SATELLITE" not in result


def test_carrier_selection_multiselect_includes_t_mobile_and_satellite_when_conditions_met(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXTENHANCED", "H55TGT9PW8BN", "carrierSelectionMultiSelect_astro",
        {
            "ultimateDestinationCountry": "US",
            "aTAKEnabledPackage_astro": "NO",
            "applicationServicesSelection_astro": "STANDALONE APP SERVICES",
        },
        workspace_id=1,
    )
    assert "T MOBILE AND T SATELLITE" in result


def test_carrier_selection_multiselect_ca_gives_bell_canada(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXTENHANCED", "H55TGT9PW8BN", "carrierSelectionMultiSelect_astro",
        {"ultimateDestinationCountry": "CA", "aTAKEnabledPackage_astro": "NO"},
        workspace_id=1,
    )
    assert result == ["BELL CANADA(PROVIDED BY MOTOROLA)", "LTE CAPABILITY NO SERVICE"]


def test_unknown_attribute_for_this_base_model_returns_none(monkeypatch):
    """carrierSelectionMultiSelect_astro has no whitelist rows at all for
    H55TGT9PW8AN -- must be None (unknown), not an empty confirmed list."""
    _patch_rdb(monkeypatch, _TABLES)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXT_BOM", "H55TGT9PW8AN", "carrierSelectionMultiSelect_astro",
        {"ultimateDestinationCountry": "US"}, workspace_id=1,
    )
    assert result is None


def test_attribute_applies_resolves_the_sibling_question_for_both_base_models(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    assert data_table_resolver.attribute_applies(
        "APXNEXT_BOM", "H55TGT9PW8AN", "wirelessCarrier_astro", workspace_id=1) is True
    assert data_table_resolver.attribute_applies(
        "APXNEXT_BOM", "H55TGT9PW8AN", "carrierSelectionMultiSelect_astro", workspace_id=1) is False
    assert data_table_resolver.attribute_applies(
        "APXNEXTENHANCED", "H55TGT9PW8BN", "carrierSelectionMultiSelect_astro", workspace_id=1) is True


def test_attribute_applies_none_when_no_sequence_data_for_base_model(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    assert data_table_resolver.attribute_applies(
        "APXNEXT_BOM", "SOME OTHER MODEL", "wirelessCarrier_astro", workspace_id=1) is None


def test_attr_ever_governed_for_cpq_model_true_for_a_real_sequence_row(monkeypatch):
    _patch_rdb(monkeypatch, _TABLES)
    assert data_table_resolver.attr_ever_governed_for_cpq_model(
        "APXNEXT_BOM", "wirelessCarrier_astro", workspace_id=1) is True


def test_attr_ever_governed_for_cpq_model_false_when_never_mentioned(monkeypatch):
    """carrierSelectionMultiSelect_astro has real sequence coverage only
    under APXNEXTENHANCED -- APXNEXT_BOM never mentions it at all."""
    _patch_rdb(monkeypatch, _TABLES)
    assert data_table_resolver.attr_ever_governed_for_cpq_model(
        "APXNEXT_BOM", "carrierSelectionMultiSelect_astro", workspace_id=1) is False


def test_attr_ever_governed_for_cpq_model_reuses_cache_across_many_attrs(monkeypatch):
    """Confirmed live (2026-08-09): calling this once per attr, per
    candidate CPQModel, per evaluate_rules_loop pass with a FRESH scan
    every time reproduced the exact O(attrs x candidates x rows) cost
    governed_attr_names_for_base_model was already built to eliminate --
    one real base model's turn took 80-325s per pass because of it. A
    shared `cache` dict must mean only ONE underlying table scan
    (`fetch_entities_by_exact_type`) regardless of how many attrs are
    checked for the same (workspace, catalog_prefix, cpq_model)."""
    calls = {"n": 0}
    real_fetch = data_table_resolver.get_cpq_rdb

    class _CountingRdb:
        def __init__(self, inner):
            self._inner = inner

        def list_ontology_types(self, workspace_id):
            return self._inner.list_ontology_types(workspace_id)

        def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
            calls["n"] += 1
            return self._inner.fetch_entities_by_exact_type(workspace_id, ontology_type)

    _patch_rdb(monkeypatch, _TABLES)
    inner = data_table_resolver.get_cpq_rdb()
    monkeypatch.setattr(data_table_resolver, "get_cpq_rdb", lambda: _CountingRdb(inner))

    cache: dict = {}
    for attr in ["wirelessCarrier_astro", "carrierSelectionMultiSelect_astro", "someOtherAttr_astro"]:
        data_table_resolver.attr_ever_governed_for_cpq_model(
            "APXNEXT_BOM", attr, workspace_id=1, cache=cache,
        )
    # One scan per ingested type across the whole cache lifetime, not one per attr.
    assert calls["n"] == len(_TABLES)


# --- Generalization: a differently-NAMED ingested table (any ontology_type
# string -- ingestion derives it from the uploaded filename, never a literal
# "whitelist"/"attrSequence") with FEWER attrN/valN pairs than APX NEXT's --
# proves the resolver is shape-driven, not hardcoded to two known types.


def test_a_new_catalogs_differently_named_table_with_fewer_attr_pairs_is_auto_discovered(monkeypatch):
    tables = {
        "SomeOtherProductsConstraintTable": [
            {"CPQModel": "NEWPRODUCT", "BaseModel": "SOME-BASE-1",
             "attr1": "colorOption_pcr", "val1": "RED",
             "attr2": "ultimateDestinationCountry", "val2": "US"},
            {"CPQModel": "NEWPRODUCT", "BaseModel": "SOME-BASE-1",
             "attr1": "colorOption_pcr", "val1": "BLUE"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    result = data_table_resolver.resolve_whitelist_values(
        "NEWPRODUCT", "SOME-BASE-1", "colorOption_pcr",
        {"ultimateDestinationCountry": "US"}, workspace_id=42,
    )
    assert result == ["BLUE", "RED"]


def test_a_new_catalogs_sequence_table_is_auto_discovered_regardless_of_ontology_type(monkeypatch):
    tables = {
        "WhateverTheyCalledIt": [
            {"CPQModel": "NEWPRODUCT", "BaseModel": "SOME-BASE-1",
             "AttrName": "colorOption_pcr", "Seq": "10", "optionOrReqFlag": "R"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    assert data_table_resolver.attribute_applies(
        "NEWPRODUCT", "SOME-BASE-1", "colorOption_pcr", workspace_id=42) is True
    assert data_table_resolver.attribute_applies(
        "NEWPRODUCT", "SOME-BASE-1", "somethingElse_pcr", workspace_id=42) is False


def test_resolve_product_cpq_model_family_matches_real_cpqmodelhierarchy_row(monkeypatch):
    """Real row from CPQModelHierarchy.csv (verified directly against the
    file): every APX NEXT product maps to the same family code "APXNEXT" --
    this is a family-level answer, not the per-product-specific one."""
    tables = {
        "CpqModelHierarchy": [
            {"productFamily": "aSTRO25", "productLine": "aSTRODevices",
             "cpqModelName": "APXNEXT", "Product": "APX NEXT ENHANCED"},
            {"productFamily": "aSTRO25", "productLine": "aSTRODevices",
             "cpqModelName": "APXNEXT", "Product": "APX NEXT MULTI"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    assert resolve_product_cpq_model_family("APX NEXT ENHANCED", workspace_id=1) == "APXNEXT"
    assert resolve_product_cpq_model_family("apx next multi", workspace_id=1) == "APXNEXT"  # case-insensitive


def test_resolve_product_cpq_model_family_none_when_product_not_in_any_hierarchy_table(monkeypatch):
    tables = {"CpqModelHierarchy": [{"cpqModelName": "APXNEXT", "Product": "APX NEXT MULTI"}]}
    _patch_rdb(monkeypatch, tables)
    assert resolve_product_cpq_model_family("SOME OTHER PRODUCT", workspace_id=1) is None


def test_similarly_suffixed_types_do_not_cross_contaminate(monkeypatch):
    """Live-discovered bug: 'Whitelist' and 'Advancedwhitelist' both end in
    'whitelist' -- the old LIKE-suffix fetch for one silently pulled in the
    other's differently-shaped rows too. Exact-type matching must keep
    them fully separate."""
    tables = {
        "Whitelist": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET"},
        ],
        "Advancedwhitelist": [
            # Real shape confirmed live: no attr1/val1 at all.
            {"CPQModel": "AUTOXPR6580IS", "RuleType": "Hide",
             "ImpactedAttr": "antennasMode_apcr", "ImpactedVal": "N/A"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    result = data_table_resolver.resolve_whitelist_values(
        "APXNEXT", "H55TGT9PW8AN", "wirelessCarrier_astro", {}, workspace_id=1,
    )
    assert result == ["ATT/FIRSTNET"]


def test_a_sparse_row_missing_a_shape_key_does_not_sink_the_whole_type(monkeypatch):
    """Live-discovered bug: a CPQModelHierarchy-shaped type was entirely
    skipped because whichever row Postgres happened to return FIRST lacked
    the 'Product' key (its source CSV cell was empty and the empty value
    was dropped, not stored). Per-row shape classification must still
    recognize every OTHER row in the same type that does have 'Product'."""
    tables = {
        "CpqModelHierarchy": [
            # Sparse row first -- no "Product" key at all, matching the
            # real one found in production.
            {"cpqModelName": "SOMETHING_NO_PRODUCT", "productFamily": "No FAMILY"},
            {"cpqModelName": "APXNEXT", "Product": "APX NEXT ENHANCED",
             "productFamily": "aSTRO25"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    fam = resolve_product_cpq_model_family("APX NEXT ENHANCED", workspace_id=1)
    assert fam == "APXNEXT"


def test_an_unrecognized_column_shape_is_skipped_not_guessed_at(monkeypatch):
    """An ingested type that matches neither known shape must not crash or
    silently be misread as one -- it's simply invisible to the resolver
    until a matching detector is added."""
    tables = {
        "SomeRandomTable": [{"partNumber": "ABC123", "imageURL": "abc123.jpg"}],
    }
    _patch_rdb(monkeypatch, tables)
    assert data_table_resolver.resolve_whitelist_values(
        "ANYTHING", "ANY", "anyAttr_astro", {}, workspace_id=1) is None
    assert data_table_resolver.attribute_applies(
        "ANYTHING", "ANY", "anyAttr_astro", workspace_id=1) is None


# --- Real Seriesmodelsmapping rows (§13 -- CPQ_CARRIER_WIRELESS_FREQBAND_
# DATA_GAP_PROOF_2026_08_07.md), confirmed live against workspace 43: for
# region=NA/country=US the Federal/International variant maps to a distinct
# "_future"-suffixed childCPQModel, not the live code every other region's
# row for the same product maps to.

_SERIES_MAPPING_ROWS = [
    {"key": "APXNEXT-11", "op1": "=", "op2": "=", "val1": "AP", "val2": "KR",
     "attr1": "modelSelectionRegion_astro", "attr2": "ultimateDestinationCountry",
     "childCPQModel": "APX NEXT INTL FED", "seriesCPQModel": "APXNEXT",
     "childCPQModelLabel": "APX NEXT™ International (Federal)"},
    {"key": "APXNEXT-29", "op1": "=", "op2": "=", "val1": "NA", "val2": "US",
     "attr1": "modelSelectionRegion_astro", "attr2": "ultimateDestinationCountry",
     "childCPQModel": "APX NEXT INTL FED_future", "seriesCPQModel": "APXNEXT",
     "childCPQModelLabel": "APX NEXT™ International (Federal)"},
]


def test_resolve_invalid_product_variant_flags_the_future_only_us_row(monkeypatch):
    """The real NA/US row maps this product to a DIFFERENT childCPQModel
    ("_future"-suffixed) than the option's own item_value -- confirms this
    is the exact live-discovered mismatch that should hide the option."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    override = data_table_resolver.resolve_invalid_product_variant(
        "APX NEXT International (Federal)", "APX NEXT INTL FED",
        {"modelSelectionRegion_astro": "NA", "ultimateDestinationCountry": "US"},
        workspace_id=1,
    )
    assert override == "APX NEXT INTL FED_future"


def test_resolve_invalid_product_variant_none_for_a_region_where_it_is_valid(monkeypatch):
    """Same product, but a region/country pair (AP/KR) whose real row maps
    to the SAME childCPQModel as the option's item_value -- genuinely valid
    here, so no override (never hide an option real data doesn't flag)."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    override = data_table_resolver.resolve_invalid_product_variant(
        "APX NEXT International (Federal)", "APX NEXT INTL FED",
        {"modelSelectionRegion_astro": "AP", "ultimateDestinationCountry": "KR"},
        workspace_id=1,
    )
    assert override is None


def test_resolve_invalid_product_variant_none_when_context_incomplete(monkeypatch):
    """No region/country filled yet -- no row's condition triples are fully
    satisfied, so nothing is flagged (never guess ahead of the real
    context)."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    override = data_table_resolver.resolve_invalid_product_variant(
        "APX NEXT International (Federal)", "APX NEXT INTL FED", {},
        workspace_id=1,
    )
    assert override is None


def test_resolve_invalid_product_variant_none_for_an_unrelated_product(monkeypatch):
    """No row's childCPQModelLabel matches this option's item_text at all
    -- None, not a guess."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    override = data_table_resolver.resolve_invalid_product_variant(
        "APX NEXT All Band", "APX NEXT ALL BAND",
        {"modelSelectionRegion_astro": "NA", "ultimateDestinationCountry": "US"},
        workspace_id=1,
    )
    assert override is None


# --- discover_cpq_models_for_base_model / find_inconsistent_filled_pairs
# (2026-08-08) -- confirmed live against workspace 43: a real base model
# (H45TGU9PW8AN) has its whitelist/attrSequence rows keyed to a more
# specific CPQModel ("APXNEXTXNSINGLE") than the product it belongs to
# maps to ("APXNEXTSINGLE") -- a genuine cross-SKU base-model-sharing case
# in the source catalog.

def test_discover_cpq_models_for_base_model_finds_the_real_variant_code(monkeypatch):
    tables = {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": "H45TGU9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET"},
            {"CPQModel": "APXNEXTXNSINGLE_PO-81514", "BaseModel": "H45TGU9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "VERIZON"},
            {"CPQModel": "APX8500-btaDelete-130624-051911-308", "BaseModel": "H45TGU9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "VERIZON"},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "wirelessCarrier_astro", "val1": "VERIZON"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    found = data_table_resolver.discover_cpq_models_for_base_model(
        "H45TGU9PW8AN", workspace_id=1,
    )
    # Only the clean, exact-base-model row's CPQModel -- stale (_PO-,
    # btaDelete) rows filtered out, and the ALL-scoped row excluded (not
    # evidence for this SPECIFIC base model).
    assert found == ["APXNEXTXNSINGLE"]


def test_find_inconsistent_filled_pairs_flags_a_real_contradiction(monkeypatch):
    """Every real row pairs Bands with a DIFFERENT band than BandPlus --
    filling both to the SAME band is a combination no row supports."""
    tables = {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "VHF",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "700/800 MHZ +"},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "700/800 MHZ",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "VHF +"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    invalid = data_table_resolver.find_inconsistent_filled_pairs(
        "APXNEXTSINGLE", "H45TGU9PW8AN",
        {
            "modelSelectionFrequencyBands_astro": "700/800 MHZ",
            "modelSelectionFrequencyBandPlus_astro": "700/800 MHZ +",
        },
        workspace_id=1,
    )
    assert invalid == {
        "modelSelectionFrequencyBands_astro", "modelSelectionFrequencyBandPlus_astro",
    }


def test_find_inconsistent_filled_pairs_none_for_a_real_valid_combination(monkeypatch):
    tables = {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "VHF",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "700/800 MHZ +"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    invalid = data_table_resolver.find_inconsistent_filled_pairs(
        "APXNEXTSINGLE", "H45TGU9PW8AN",
        {
            "modelSelectionFrequencyBands_astro": "VHF",
            "modelSelectionFrequencyBandPlus_astro": "700/800 MHZ +",
        },
        workspace_id=1,
    )
    assert invalid == set()


def test_find_inconsistent_filled_pairs_ignores_unlinked_attrs(monkeypatch):
    """Two filled attrs that never co-occur as attr1/attr2 in any row are
    not "linked" at all -- never flagged, regardless of their values."""
    tables = {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET"},
        ],
    }
    _patch_rdb(monkeypatch, tables)
    invalid = data_table_resolver.find_inconsistent_filled_pairs(
        "APXNEXTSINGLE", "H45TGU9PW8AN",
        {"wirelessCarrier_astro": "ATT/FIRSTNET", "batteryType_astro": "STANDARD"},
        workspace_id=1,
    )
    assert invalid == set()
