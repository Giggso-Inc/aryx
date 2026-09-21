"""search_products_combined() merges Phase 1 (graph, search_by_feature) and
Phase 2 (Postgres Data Table, search_products_by_region/_feature) search
results on a shared model-name join key -- see Phase2_DataTable_Schema_
Audit.md §4 step 4. Data Tables never reach FalkorDB, so this is the only
way a caller sees both a region/feature constraint AND graph-side context
(hidden_by_rule, etc.) for the same product in one call.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.feature_search import search_products_combined


def _reader_returning(by_name: dict[str, list[dict]]) -> MagicMock:
    """A fake GraphReader whose find_entities() return value depends on the
    `name` kwarg it was called with -- lets tests distinguish the direct
    Phase 1 call from search_products_combined's own per-model
    cross-reference lookups."""
    reader = MagicMock()

    def _find_entities(ontology_type=None, name=None, attrs=None, limit=50):
        return by_name.get(name, [])

    reader.find_entities.side_effect = _find_entities
    return reader


def _reader_with_contains_semantics(entities: list[dict]) -> MagicMock:
    """A fake GraphReader whose find_entities(name=...) mirrors FalkorDB's
    real predicate (toLower(e.name) CONTAINS toLower($name), reader.py:196)
    -- a case-insensitive SUBSTRING match, not equality, and NOT ordered by
    relevance. `entities` is returned in the order given, so a query for a
    short model name can return an unrelated longer name FIRST if it's
    earlier in the list -- exactly the ambiguity PR #331's review (M1)
    flagged the old limit=1-take-candidates[0] code as trusting blindly.
    """
    reader = MagicMock()

    def _find_entities(ontology_type=None, name=None, attrs=None, limit=50):
        if not name:
            return list(entities)[:limit]
        needle = name.lower()
        return [e for e in entities if needle in (e.get("name") or "").lower()][:limit]

    reader.find_entities.side_effect = _find_entities
    return reader


def _engine_with_no_hiding_rules() -> MagicMock:
    """An engine where every candidate resolves to "not a configurable
    product" -- keeps these merge tests focused on the join logic, not
    search_by_feature's own hiding-rule behavior (already covered by
    test_feature_search_2026_09_15.py)."""
    engine = MagicMock()
    engine.load_product_config.side_effect = Exception("not a configurable product")
    return engine


class TestDataTableOnlyMatches:
    def test_region_only_match_with_no_graph_presence(self):
        """A Data-Table-only hit (model not found in the graph at all) must
        still be returned, with graph_entity=None and source=["data_table"]."""
        reader = _reader_returning({})  # nothing exists in the graph
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APXNEXTSINGLE", "attribute": "modelSelectionbaseModel_astro",
                 "value": "H45TGT9PW8AN", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert len(results) == 1
        assert results[0]["model"] == "APXNEXTSINGLE"
        assert results[0]["source"] == ["data_table"]
        assert results[0]["graph_entity"] is None
        assert results[0]["data_table_matches"][0]["value"] == "H45TGT9PW8AN"
        mock_region.assert_called_once_with("NA", 1, "")

    def test_data_table_match_enriched_with_graph_context_when_present(self):
        """When a Postgres-side match's model DOES exist in the graph, the
        merge must cross-reference and attach it, even though the caller
        passed no direct graph filter."""
        reader = _reader_returning({
            "APXNEXTSINGLE": [{"id": 1, "type": "Product", "name": "APXNEXTSINGLE"}],
        })
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APXNEXTSINGLE", "attribute": "x", "value": "y", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert results[0]["source"] == ["data_table", "graph"]
        assert results[0]["graph_entity"]["name"] == "APXNEXTSINGLE"

    def test_multiple_rows_for_the_same_model_are_pooled_not_duplicated(self):
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APXNEXTSINGLE", "attribute": "a", "value": "1", "region": "NA"},
                {"model": "APXNEXTSINGLE", "attribute": "b", "value": "2", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert len(results) == 1  # one merged entry per model, not per row
        assert len(results[0]["data_table_matches"]) == 2

    def test_feature_search_wired_through_with_cpq_model_scope(self):
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_feature") as mock_feature:
            mock_feature.return_value = [
                {"model": "APX1000", "base_model": "H45TGT9PW8AN",
                 "attribute": "systemEnhancementFeatureType_astro", "value": "AES-256 Encryption"},
            ]
            results = search_products_combined(
                reader, engine, workspace_id=1,
                feature_label="Feature Type", feature_value="Encryption",
                cpq_model="APX1000",
            )

        mock_feature.assert_called_once_with(
            "Feature Type", "Encryption", 1, cpq_model="APX1000", catalog_prefix="",
        )
        assert results[0]["model"] == "APX1000"
        assert results[0]["source"] == ["data_table"]

    def test_feature_value_without_label_never_calls_data_table_search(self):
        """feature_label and feature_value must both be given -- a partial
        pair (e.g. value alone) is not enough to resolve a variable name,
        so the search must be skipped rather than called with garbage."""
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_feature") as mock_feature:
            results = search_products_combined(
                reader, engine, workspace_id=1, feature_value="Encryption",
            )

        mock_feature.assert_not_called()
        assert results == []


class TestGraphOnlyMatches:
    def test_graph_filter_with_no_region_or_feature_never_calls_data_table_search(self):
        """A caller who only wants Phase 1's graph search must not pay for
        an unrelated Postgres scan."""
        reader = _reader_returning({
            "Widget": [{"id": 1, "type": "Product", "name": "Widget"}],
        })
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region, \
             patch("aryx.graph.feature_search.search_products_by_feature") as mock_feature:
            results = search_products_combined(reader, engine, workspace_id=1, name="Widget")

        mock_region.assert_not_called()
        mock_feature.assert_not_called()
        assert results[0]["model"] == "Widget"
        assert results[0]["source"] == ["graph"]
        assert results[0]["data_table_matches"] == []

    def test_no_filters_at_all_returns_empty_without_any_scan(self):
        """Neither a graph filter nor a region/feature query given -- must
        not silently run an unbounded 'browse everything' graph scan."""
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region, \
             patch("aryx.graph.feature_search.search_products_by_feature") as mock_feature:
            results = search_products_combined(reader, engine, workspace_id=1)

        mock_region.assert_not_called()
        mock_feature.assert_not_called()
        reader.find_entities.assert_not_called()
        assert results == []


class TestJoinKeyNormalization:
    def test_join_key_is_case_and_whitespace_insensitive(self):
        """A graph entity named ' apx1000 ' and a Data Table row for
        'APX1000' must merge into ONE entry, not two."""
        reader = _reader_returning({
            "  apx1000  ": [{"id": 1, "type": "Product", "name": "  apx1000  "}],
        })
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APX1000", "attribute": "a", "value": "1", "region": "NA"},
            ]
            results = search_products_combined(
                reader, engine, workspace_id=1, region="NA", name="  apx1000  ",
            )

        assert len(results) == 1
        assert set(results[0]["source"]) == {"data_table", "graph"}

    def test_rows_with_no_model_name_are_skipped_not_crashed_on(self):
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": None, "attribute": "a", "value": "1", "region": "NA"},
                {"model": "", "attribute": "b", "value": "2", "region": "NA"},
                {"model": "APXNEXTSINGLE", "attribute": "c", "value": "3", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert len(results) == 1
        assert results[0]["model"] == "APXNEXTSINGLE"


class TestLimit:
    def test_limit_caps_the_merged_result_count(self):
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": f"MODEL_{i}", "attribute": "a", "value": "1", "region": "NA"}
                for i in range(5)
            ]
            results = search_products_combined(
                reader, engine, workspace_id=1, region="NA", limit=2,
            )

        assert len(results) == 2


class TestEnrichmentRequiresExactJoinKeyMatch:
    """PR #331 review (M1): the enrichment step used to accept
    candidates[0] from a CONTAINS query unconditionally -- meaning a
    Data-Table-only match for a short model name could be silently
    enriched with an unrelated, longer name's hidden_by_rule/graph
    context. Fixed: only a candidate whose OWN join key matches the
    entry's key exactly is ever attached."""

    def test_substring_collision_does_not_win_over_the_exact_match(self):
        # "APX100-Pro" is returned FIRST by the fake reader and also
        # matches the "APX1" CONTAINS query (naive candidates[0] would pick
        # it) -- the real "APX1" entity is second. The fix must attach the
        # exact match (APX1, id=2), never the unrelated substring hit.
        reader = _reader_with_contains_semantics([
            {"id": 1, "type": "Product", "name": "APX100-Pro"},
            {"id": 2, "type": "Product", "name": "APX1"},
        ])
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APX1", "attribute": "a", "value": "1", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert len(results) == 1
        assert results[0]["graph_entity"]["id"] == 2
        assert results[0]["graph_entity"]["name"] == "APX1"
        assert set(results[0]["source"]) == {"data_table", "graph"}

    def test_substring_collision_with_no_exact_match_present_leaves_graph_entity_none(self):
        # Only the unrelated substring hit exists -- no real "APX1" entity
        # at all. Must NOT fall back to the wrong candidate; must leave
        # graph_entity unset instead.
        reader = _reader_with_contains_semantics([
            {"id": 1, "type": "Product", "name": "APX100-Pro"},
        ])
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APX1", "attribute": "a", "value": "1", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert len(results) == 1
        assert results[0]["graph_entity"] is None
        assert results[0]["source"] == ["data_table"]

    def test_exact_match_among_several_contains_hits_is_still_found(self):
        # The real "APX1" entity exists too, just not first in insertion
        # order -- the fix must still find and attach it, not give up
        # entirely just because the naive first-hit was wrong.
        reader = _reader_with_contains_semantics([
            {"id": 1, "type": "Product", "name": "APX100-Pro"},
            {"id": 2, "type": "Product", "name": "APX10"},
            {"id": 3, "type": "Product", "name": "APX1"},
        ])
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APX1", "attribute": "a", "value": "1", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert results[0]["graph_entity"]["id"] == 3
        assert results[0]["graph_entity"]["name"] == "APX1"
        assert set(results[0]["source"]) == {"data_table", "graph"}

    def test_no_contains_hit_at_all_leaves_graph_entity_none(self):
        reader = _reader_with_contains_semantics([
            {"id": 1, "type": "Product", "name": "SomethingElse"},
        ])
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": "APX1", "attribute": "a", "value": "1", "region": "NA"},
            ]
            results = search_products_combined(reader, engine, workspace_id=1, region="NA")

        assert results[0]["graph_entity"] is None
        assert results[0]["source"] == ["data_table"]


class TestLimitAppliedBeforeEnrichment:
    """PR #331 review (M2): limit was only applied to the final result
    list, so a broad Postgres-side match against hundreds of models ran
    the per-model graph-enrichment lookup for EVERY match before any
    truncation happened. Fixed: limit is applied to the merged model set
    before the enrichment loop runs."""

    def test_enrichment_lookup_runs_at_most_limit_times(self):
        reader = _reader_returning({})  # find_entities always returns []
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": f"MODEL_{i}", "attribute": "a", "value": "1", "region": "NA"}
                for i in range(50)
            ]
            search_products_combined(reader, engine, workspace_id=1, region="NA", limit=3)

        # One find_entities call per enriched model, at most `limit` of
        # them -- not once per one of the 50 matched rows.
        assert reader.find_entities.call_count <= 3

    def test_result_count_and_enrichment_count_both_respect_limit(self):
        reader = _reader_returning({})
        engine = _engine_with_no_hiding_rules()

        with patch("aryx.graph.feature_search.search_products_by_region") as mock_region:
            mock_region.return_value = [
                {"model": f"MODEL_{i}", "attribute": "a", "value": "1", "region": "NA"}
                for i in range(100)
            ]
            results = search_products_combined(
                reader, engine, workspace_id=1, region="NA", limit=5,
            )

        assert len(results) == 5
        assert reader.find_entities.call_count == 5
