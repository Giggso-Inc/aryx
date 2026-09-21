"""OracleGraphReader.find_entities(attrs=...) — Oracle-side counterpart to
tests/test_graph_find_entities_attrs_2026_09_15.py's Cypher/FalkorDB
coverage.

Root cause this closes (Raven Review on PR #344, aryx-enterprise): commit
e564b6bb ported find_entities(attrs=...) for the FalkorDB-backed
GraphReader only. graph/feature_search.py's search_by_feature() and
search_products_combined() call reader.find_entities(..., attrs=attrs, ...)
polymorphically and unconditionally (even when attrs is None), and
container.py returns OracleGraphReader whenever ARYX_DB_BACKEND=oci --
dev_oci's own real deployment. Since OracleGraphReader.find_entities() had
no attrs parameter at all, every graph-side region/feature search crashed
with TypeError on that backend: masked as a silent empty result via chat
(ask_feature_region_search.py's broad except Exception) and a hard 500 via
the direct POST /entities/search API (graph_api.py, no exception handling
at all). Confirmed via grep: none of e564b6bb's own 8 new test files
reference OracleGraphReader or the oci_graph backend, so this gap shipped
untested.

Oracle-specific correctness note: the original follow-up plan (docs/
oci-oracle/DEV_RV_MSI_INTO_DEV_OCI_INTEGRATION_PLAN_2026-09-21.md Part B)
proposed binding the JSON key itself via '$.' || :key_N -- verified via
research this does NOT work (Oracle raises ORA-40454, "path expression not
a literal": JSON_VALUE's path argument must be a compile-time literal, not
a bind variable or runtime expression). The actual fix keeps the same
regex-validated-key approach but embeds the validated key directly into
the literal path text (like Cypher's e.{key} property interpolation),
binding only the value.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.graph.oracle_graph_reader import OracleGraphReader


def _make_reader(fetchall_return=None):
    with patch("aryx.store.oracle_pool.get_oracle_pool") as mock_get_pool:
        mock_pool = MagicMock()
        mock_get_pool.return_value = mock_pool
        reader = OracleGraphReader("tcps://test:1522/db", workspace_id=7)
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_return or []
    mock_pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
    return reader, cur


def test_attrs_predicate_adds_json_value_clause_and_binds_the_value():
    reader, cur = _make_reader()
    reader.find_entities(ontology_type="Product", attrs={"secureEncryptionType_astro": "AES256"})

    sql, params = cur.execute.call_args[0]
    assert "type = :typ" in sql
    assert "JSON_VALUE(attributes, '$.secureEncryptionType_astro')" in sql
    assert params["typ"] == "Product"
    assert params["attr_val_0"] == "AES256"
    # The key must be a literal in the SQL text, never itself bound --
    # JSON_VALUE's path argument can't be a bind variable (ORA-40454).
    assert "attr_key_0" not in params


def test_multiple_attrs_are_anded_together():
    reader, cur = _make_reader()
    reader.find_entities(attrs={"region": "NA", "customerType": "Federal"})

    sql, params = cur.execute.call_args[0]
    assert " AND " in sql
    assert "JSON_VALUE(attributes, '$.region')" in sql
    assert "JSON_VALUE(attributes, '$.customerType')" in sql
    assert params["attr_val_0"] == "NA"
    assert params["attr_val_1"] == "Federal"


def test_invalid_attribute_key_rejected_not_interpolated_raw():
    """Property/JSON-path keys can't be parameterized the way values can --
    an unvalidated key would be a straight injection path into the literal
    SQL text itself (the same reasoning as the Cypher-side test)."""
    reader, _cur = _make_reader()
    with pytest.raises(ValueError, match="invalid attribute key"):
        reader.find_entities(attrs={"x') OR '1'='1": "y"})


def test_no_attrs_behaves_exactly_as_before():
    reader, cur = _make_reader()
    reader.find_entities(ontology_type="Product", name="Astro")

    sql, params = cur.execute.call_args[0]
    assert "JSON_VALUE" not in sql
    assert "attr_val_0" not in params
