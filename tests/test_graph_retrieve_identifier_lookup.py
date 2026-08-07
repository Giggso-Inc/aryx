"""Regression coverage for the multi-identifier attribute-value lookup.

Bug this closes: an entity's e.name is chosen from a single hardcoded
priority list (aryx.explore._NAME_KEYS), never any other attribute — so a
row with two equally-real identifiers (e.g. an FSC and an NSN column on the
same report row) is only ever findable by whichever field won that list. An
NSN lookup returns "not found" even though the record exists, while an FSC
lookup on the same report succeeds. These tests pin the fix: a term that
looks identifier-shaped and misses every existing lookup path falls through
to a dynamic, schema-agnostic attribute-value scan — never naming a specific
field/column.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.graph.retrieve import _looks_like_identifier, _lookup, gather


class TestLooksLikeIdentifier:
    def test_long_digit_run_qualifies(self):
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 6
            assert _looks_like_identifier("1560015864867") is True

    def test_long_alnum_code_qualifies(self):
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 6
            assert _looks_like_identifier("APX6500X") is True

    def test_short_term_does_not_qualify(self):
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 6
            assert _looks_like_identifier("5985") is False

    def test_term_with_spaces_does_not_qualify(self):
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 6
            assert _looks_like_identifier("APX NEXT RADIO") is False

    def test_word_without_digit_does_not_qualify(self):
        """A long common word must not qualify — the digit requirement is
        what keeps this a cost gate, not a length-only vocabulary check."""
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 6
            assert _looks_like_identifier("battery") is False

    def test_threshold_is_configurable_not_hardcoded(self):
        """A different configured minimum must actually change the outcome —
        proves this reads live config, not a baked-in constant."""
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_min_length = 20
            assert _looks_like_identifier("1560015864867") is False


class TestLookupAttributeValueFallback:
    def _reader(self, name_hits=None, attr_hits=None):
        reader = MagicMock()
        reader.get_entity.return_value = None
        reader.find_entities.return_value = list(name_hits or [])
        reader.find_entity_by_attribute_value.return_value = list(attr_hits or [])
        return reader

    def test_falls_through_to_attribute_value_when_name_search_misses(self):
        """The exact live-confirmed bug: NSN isn't findable by name, but IS
        findable as a plain attribute value."""
        reader = self._reader(
            name_hits=[],
            attr_hits=[{"id": 1, "type": "Aviation", "name": "1560"}],
        )
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_lookup_enabled = True
            mock_cfg.return_value.identifier_min_length = 6
            mock_cfg.return_value.identifier_lookup_limit = 10
            hits, calls = _lookup(reader, "1560015864867")

        assert len(hits) == 1
        reader.find_entity_by_attribute_value.assert_called_once_with(
            "1560015864867", limit=10)
        assert any("find_by_attribute_value" in c for c in calls)

    def test_does_not_fire_when_name_search_already_found_something(self):
        """FSC-style lookups (already findable via e.name) must never pay
        for the extra fallback call."""
        reader = self._reader(
            name_hits=[{"id": 2, "type": "Aviation", "name": "5985"}],
        )
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_lookup_enabled = True
            mock_cfg.return_value.identifier_min_length = 6
            mock_cfg.return_value.identifier_lookup_limit = 10
            hits, calls = _lookup(reader, "5985")

        assert len(hits) == 1
        reader.find_entity_by_attribute_value.assert_not_called()
        assert calls == []

    def test_does_not_fire_for_non_identifier_shaped_terms(self):
        """An ordinary short/common-word question term must never trigger
        the property scan, regardless of whether name search missed —
        this is the cost gate, not a field restriction."""
        reader = self._reader(name_hits=[])
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_lookup_enabled = True
            mock_cfg.return_value.identifier_min_length = 6
            mock_cfg.return_value.identifier_lookup_limit = 10
            hits, calls = _lookup(reader, "battery")

        assert hits == []
        reader.find_entity_by_attribute_value.assert_not_called()
        assert calls == []

    def test_kill_switch_disables_the_fallback_entirely(self):
        reader = self._reader(
            name_hits=[],
            attr_hits=[{"id": 1, "type": "Aviation", "name": "1560"}],
        )
        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_lookup_enabled = False
            mock_cfg.return_value.identifier_min_length = 6
            hits, calls = _lookup(reader, "1560015864867")

        assert hits == []
        reader.find_entity_by_attribute_value.assert_not_called()
        assert calls == []


class TestGatherLogsTheFallbackCall:
    def test_gather_records_find_by_attribute_value_in_calls(self):
        reader = MagicMock()
        reader.get_entity.return_value = None
        reader.find_entities.return_value = []
        reader.find_entity_by_attribute_value.return_value = [
            {"id": 1, "type": "Aviation", "name": "1560"},
        ]
        reader.neighbors.return_value = []
        reader.provenance.return_value = []

        with patch("aryx.graph.retrieve.get_settings") as mock_cfg:
            mock_cfg.return_value.identifier_lookup_enabled = True
            mock_cfg.return_value.identifier_min_length = 6
            mock_cfg.return_value.identifier_lookup_limit = 10
            entities, calls = gather(reader, ["1560015864867"])

        assert len(entities) == 1
        assert any("find_by_attribute_value" in c for c in calls)


class TestFindEntityByAttributeValue:
    def test_queries_any_property_not_a_named_field(self):
        """Proves the Cypher never names a specific column — it's a dynamic
        any(k in keys(e)...) scan."""
        from aryx.graph.reader import GraphReader

        reader = GraphReader.__new__(GraphReader)
        with patch.object(GraphReader, "_query", return_value=[]) as mock_query, \
             patch("aryx.graph.reader.get_settings") as mock_cfg:
            mock_cfg.return_value.graph_query_limit = 2000
            reader.find_entity_by_attribute_value("1560015864867", limit=10)

        cypher, params = mock_query.call_args[0]
        assert "any(" in cypher
        assert "keys(e)" in cypher
        assert params == {"value": "1560015864867"}
        # No hardcoded field name anywhere in the query text.
        for banned in ("nsn", "fsc", "pr_number"):
            assert banned not in cypher.lower()
