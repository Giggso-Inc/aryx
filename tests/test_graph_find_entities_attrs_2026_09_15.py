"""find_entities() previously only filtered by ontology_type (exact) and
name (substring) -- attributes were node properties, never a search
predicate, closing off "find products with feature X" entirely (confirmed
live via investigation 2026-09-15: no filter path anywhere touches
attribute values). attrs=... adds that predicate, ANDed with type/name.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.graph.reader import GraphReader


def _reader() -> GraphReader:
    with patch("aryx.graph.reader.FalkorDB"):
        return GraphReader("redis://localhost:6379")


def test_attrs_predicate_adds_where_clause_and_params() -> None:
    reader = _reader()
    with patch.object(reader, "_query", return_value=[]) as mock_query:
        reader.find_entities(ontology_type="Product", attrs={"secureEncryptionType_astro": "AES256"})

    cypher, params = mock_query.call_args[0]
    assert "e.type = $type" in cypher
    assert "e.secureEncryptionType_astro" in cypher
    assert params["type"] == "Product"
    assert params["attr_val_0"] == "AES256"


def test_multiple_attrs_are_anded_together() -> None:
    reader = _reader()
    with patch.object(reader, "_query", return_value=[]) as mock_query:
        reader.find_entities(attrs={"region": "NA", "customerType": "Federal"})

    cypher, params = mock_query.call_args[0]
    assert " AND " in cypher
    assert params["attr_val_0"] == "NA"
    assert params["attr_val_1"] == "Federal"


def test_invalid_attribute_key_rejected_not_interpolated_raw() -> None:
    """Property names can't be parameterized in Cypher the way values can --
    an unvalidated key would be a straight injection path into the query
    string itself."""
    reader = _reader()
    with patch.object(reader, "_query", return_value=[]):
        with pytest.raises(ValueError, match="invalid attribute key"):
            reader.find_entities(attrs={"e.type} OR 1=1 //": "x"})


def test_no_attrs_behaves_exactly_as_before() -> None:
    reader = _reader()
    with patch.object(reader, "_query", return_value=[]) as mock_query:
        reader.find_entities(ontology_type="Product", name="Astro")

    cypher, params = mock_query.call_args[0]
    assert "attr_val_0" not in params
