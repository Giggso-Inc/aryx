"""Tests for Phase 2 of the feature/region search plan (2026-09-15/16 andie
analysis): resolve_variable_name_for_role, search_products_by_region,
search_products_by_feature -- see Phase2_DataTable_Schema_Audit.md.

Same fake-rdb pattern as tests/test_cpq_data_table_resolver.py: a fake rdb
(monkeypatched onto get_cpq_rdb) stands in for Postgres, keyed by ontology
type -> list of ingested-row dicts exactly as a real CSV upload produces
them (JSONB attributes keyed by the CSV's own headers).

resolve_variable_name_for_role calls get_cpq_rdb() bound in
data_table_product's own module namespace; search_products_by_region/
search_products_by_feature route through _load_all_tables(), which calls
get_cpq_rdb() bound in data_table_loader's namespace instead -- _patch_rdb
patches both, matching test_cpq_data_table_resolver.py's own precedent for
why a hub-level patch (aryx.cpq.data_table.data_table_resolver.get_cpq_rdb)
would silently not intercept either call.
"""
from __future__ import annotations

import pytest

from aryx.cpq.data_table import data_table_loader, data_table_product
from aryx.cpq.data_table.data_table_resolver import (
    _clear_tables_cache,
    resolve_variable_name_for_role,
    search_products_by_feature,
    search_products_by_region,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _clear_tables_cache()
    yield
    _clear_tables_cache()


class _FakeRdb:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def list_ontology_types(self, workspace_id):
        return list(self._tables.keys())

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        rows = self._tables.get(ontology_type, [])
        return [(i, r) for i, r in enumerate(rows, start=1)]

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        return {
            otype: [(i, r) for i, r in enumerate(rows, start=1)]
            for otype, rows in self._tables.items()
        }


def _patch_rdb(monkeypatch, tables: dict[str, list[dict]]) -> None:
    fake = _FakeRdb(tables)
    monkeypatch.setattr(data_table_product, "get_cpq_rdb", lambda: fake)
    monkeypatch.setattr(data_table_loader, "get_cpq_rdb", lambda: fake)


# ---------------------------------------------------------------------------
# resolve_variable_name_for_role
# ---------------------------------------------------------------------------

_ATTR_VAR_MAPPING_ROWS = [
    {"cpqModel": "APX1000", "group": "", "attributeName": "Base Model",
     "attributeVariable": "modelSelectionbaseModel_astro"},
    {"cpqModel": "APX1000", "group": "", "attributeName": "Region",
     "attributeVariable": "modelSelectionRegion_astro"},
    {"cpqModel": "APX1000", "group": "System Enhancements",
     "attributeName": "Feature Type",
     "attributeVariable": "systemEnhancementFeatureType_astro"},
    # A different model uses a DIFFERENT variable name for the same role --
    # confirms the resolver is per-model, not a global label->name table.
    {"cpqModel": "APX2000", "group": "System Enhancements",
     "attributeName": "Feature Type",
     "attributeVariable": "sysEnhFeatureType_apx2000"},
]


class TestResolveVariableNameForRole:
    def test_resolves_real_confirmed_mapping(self, monkeypatch):
        _patch_rdb(monkeypatch, {"AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS})
        result = resolve_variable_name_for_role("APX1000", "Feature Type", workspace_id=1)
        assert result == "systemEnhancementFeatureType_astro"

    def test_case_insensitive_role_and_model_matching(self, monkeypatch):
        _patch_rdb(monkeypatch, {"AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS})
        result = resolve_variable_name_for_role("apx1000", "feature type", workspace_id=1)
        assert result == "systemEnhancementFeatureType_astro"

    def test_same_role_different_variable_per_model(self, monkeypatch):
        _patch_rdb(monkeypatch, {"AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS})
        assert resolve_variable_name_for_role(
            "APX2000", "Feature Type", workspace_id=1,
        ) == "sysEnhFeatureType_apx2000"

    def test_no_match_returns_none_not_a_guess(self, monkeypatch):
        _patch_rdb(monkeypatch, {"AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS})
        assert resolve_variable_name_for_role("APX1000", "Encryption Level", workspace_id=1) is None

    def test_unknown_model_returns_none(self, monkeypatch):
        _patch_rdb(monkeypatch, {"AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS})
        assert resolve_variable_name_for_role("APX_NONEXISTENT", "Region", workspace_id=1) is None

    def test_ambiguous_two_distinct_variables_returns_none(self, monkeypatch):
        """A genuine tie (2+ distinct variable names for the same model+role)
        must never be guessed across -- matches resolve_region_allow_value's
        own never-guess-on-a-tie convention."""
        ambiguous_rows = _ATTR_VAR_MAPPING_ROWS + [
            {"cpqModel": "APX1000", "group": "", "attributeName": "Region",
             "attributeVariable": "modelSelectionRegion_ALT_astro"},
        ]
        _patch_rdb(monkeypatch, {"AttrToVarMapping": ambiguous_rows})
        assert resolve_variable_name_for_role("APX1000", "Region", workspace_id=1) is None

    def test_non_attr_var_mapping_rows_are_ignored(self, monkeypatch):
        """Rows from an unrelated ingested type (missing the required
        columns) must never be mistaken for attrToVarMapping rows."""
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeOtherWhitelist": [{"CPQModel": "APX1000", "BaseModel": "X",
                                     "attr1": "Feature Type", "val1": "Region"}],
        })
        assert resolve_variable_name_for_role(
            "APX1000", "Feature Type", workspace_id=1,
        ) == "systemEnhancementFeatureType_astro"


# ---------------------------------------------------------------------------
# search_products_by_region
# ---------------------------------------------------------------------------

_REGION_RULE_ROWS = [
    # Real shape confirmed in resolve_region_allow_value's own docstring:
    # model/value/region/ruleType/attribute[/UDCC].
    {"model": "APXNEXTSINGLE", "value": "H45TGT9PW8AN", "region": "NA",
     "ruleType": "ALLOW", "attribute": "modelSelectionbaseModel_astro"},
    {"model": "APXNEXTSINGLE", "value": "H99TGT9PW8XX", "region": "EMEA",
     "ruleType": "ALLOW", "attribute": "modelSelectionbaseModel_astro"},
    {"model": "APXNEXTDUAL", "value": "H45TGT9PW8AN", "region": "NA",
     "ruleType": "ALLOW", "attribute": "modelSelectionbaseModel_astro"},
    # A DISALLOW row for the same region must never appear in ALLOW results.
    {"model": "APXNEXTSINGLE", "value": "BLOCKEDVALUE", "region": "NA",
     "ruleType": "DISALLOW", "attribute": "modelSelectionbaseModel_astro"},
]


class TestSearchProductsByRegion:
    def test_returns_every_allow_row_for_the_region(self, monkeypatch):
        _patch_rdb(monkeypatch, {"NewCountryRegMapping": _REGION_RULE_ROWS})
        results = search_products_by_region("NA", workspace_id=1)
        models = {r["model"] for r in results}
        assert models == {"APXNEXTSINGLE", "APXNEXTDUAL"}
        assert all(r["region"] == "NA" for r in results)

    def test_excludes_disallow_rows(self, monkeypatch):
        _patch_rdb(monkeypatch, {"NewCountryRegMapping": _REGION_RULE_ROWS})
        results = search_products_by_region("NA", workspace_id=1)
        assert not any(r["value"] == "BLOCKEDVALUE" for r in results)

    def test_case_insensitive_region_matching(self, monkeypatch):
        _patch_rdb(monkeypatch, {"NewCountryRegMapping": _REGION_RULE_ROWS})
        results = search_products_by_region("na", workspace_id=1)
        assert len(results) == 2

    def test_region_with_no_matches_returns_empty_list(self, monkeypatch):
        _patch_rdb(monkeypatch, {"NewCountryRegMapping": _REGION_RULE_ROWS})
        assert search_products_by_region("APAC", workspace_id=1) == []

    def test_duplicate_triples_are_deduplicated(self, monkeypatch):
        duplicated = _REGION_RULE_ROWS + [dict(_REGION_RULE_ROWS[0])]
        _patch_rdb(monkeypatch, {"NewCountryRegMapping": duplicated})
        results = search_products_by_region("NA", workspace_id=1)
        assert len(results) == 2  # not 3 -- the exact duplicate collapses


# ---------------------------------------------------------------------------
# search_products_by_feature
# ---------------------------------------------------------------------------

_CONSTRAINT_ROWS = [
    {"CPQModel": "APX1000", "BaseModel": "H45TGT9PW8AN",
     "attr1": "systemEnhancementFeatureType_astro", "val1": "AES-256 Encryption"},
    {"CPQModel": "APX1000", "BaseModel": "H45TGT9PW8AN",
     "attr1": "systemEnhancementFeatureType_astro", "val1": "GPS Tracking"},
    {"CPQModel": "APX1000", "BaseModel": "H99TGT9PW8XX",
     "attr1": "systemEnhancementFeatureType_astro", "val1": "AES-256 Encryption"},
    # Different model, different variable name for "Feature Type" -- proves
    # the per-model label resolution actually matters, not just a constant.
    {"CPQModel": "APX2000", "BaseModel": "H55TGT9PW8ZZ",
     "attr1": "sysEnhFeatureType_apx2000", "val1": "AES-256 Encryption"},
    # A row for an unrelated attribute must never be mistaken for a feature match.
    {"CPQModel": "APX1000", "BaseModel": "H45TGT9PW8AN",
     "attr1": "modelSelectionRegion_astro", "val1": "NA"},
]


class TestSearchProductsByFeature:
    def test_finds_matching_rows_by_resolved_variable_name(self, monkeypatch):
        """Without a cpq_model filter, every ingested model is searched via
        its OWN resolved variable name -- APX1000 (2 encrypted base_models)
        and APX2000 (its own row, via a different real variable name) all
        legitimately match "Feature Type" contains "Encryption"."""
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature("Feature Type", "Encryption", workspace_id=1)
        base_models = {r["base_model"] for r in results}
        assert base_models == {"H45TGT9PW8AN", "H99TGT9PW8XX", "H55TGT9PW8ZZ"}

    def test_substring_match_not_exact_equality(self, monkeypatch):
        """'Encryption' must match 'AES-256 Encryption' -- CONTAINS
        semantics, matching find_entities(attrs=...)'s own convention on
        the graph side. All 3 real encryption rows across both models
        match a case-insensitive substring search."""
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature("Feature Type", "encryption", workspace_id=1)
        assert len(results) == 3

    def test_different_models_use_their_own_resolved_variable_name(self, monkeypatch):
        """APX1000 and APX2000 use different real variable names for
        'Feature Type' -- both must still be found by the same human label."""
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature("Feature Type", "Encryption", workspace_id=1)
        models = {r["model"] for r in results}
        assert models == {"APX1000", "APX2000"}

    def test_cpq_model_filter_scopes_the_search(self, monkeypatch):
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature(
            "Feature Type", "Encryption", workspace_id=1, cpq_model="APX2000",
        )
        assert len(results) == 1
        assert results[0]["model"] == "APX2000"

    def test_unresolvable_label_yields_no_matches_not_an_error(self, monkeypatch):
        """A label with no attrToVarMapping row for a given model must be
        skipped for that model, not raise."""
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature("Encryption Level", "anything", workspace_id=1)
        assert results == []

    def test_unrelated_attribute_rows_are_not_matched(self, monkeypatch):
        _patch_rdb(monkeypatch, {
            "AttrToVarMapping": _ATTR_VAR_MAPPING_ROWS,
            "SomeConstraintTable": _CONSTRAINT_ROWS,
        })
        results = search_products_by_feature("Feature Type", "NA", workspace_id=1)
        assert results == []  # the Region=NA row must not leak in
