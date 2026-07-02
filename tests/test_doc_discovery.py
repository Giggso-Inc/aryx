"""Tests for _xml_to_csvs, read_files, and _display_name in pipeline.doc_discovery."""
import csv
import io
from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery import _xml_to_csvs


def _rows(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode())))


def test_empty_xml_no_repeating_children_falls_back_to_raw():
    xml = b"<root></root>"
    results = _xml_to_csvs(xml, "test")
    assert results == [(xml, "test.csv")]


def test_single_repeating_tag_produces_one_csv():
    xml = b"""<root>
        <item id="1" name="alpha"/>
        <item id="2" name="beta"/>
        <item id="3" name="gamma"/>
    </root>"""
    results = _xml_to_csvs(xml, "data")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert len(rows) == 3
    assert all(r["_element_type"] == "item" for r in rows)


def test_multi_type_xml_produces_multiple_csvs():
    xml = b"""<catalogue>
        <product id="p1" name="Widget"/>
        <product id="p2" name="Gadget"/>
        <category id="c1" label="Electronics"/>
        <category id="c2" label="Tools"/>
    </catalogue>"""
    results = _xml_to_csvs(xml, "catalogue")
    types_found = {name.rsplit("_", 1)[-1].replace(".csv", "") for _, name in results}
    assert "product" in types_found
    assert "category" in types_found


def test_namespace_prefixed_tags_are_stripped():
    xml = b"""<root xmlns:ns="urn:test">
        <ns:Widget id="1"/>
        <ns:Widget id="2"/>
        <ns:Widget id="3"/>
    </root>"""
    results = _xml_to_csvs(xml, "ns_test")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r["_element_type"] == "Widget" for r in rows)


def test_elements_with_text_only_use_text_field():
    xml = b"""<root>
        <note>alpha</note>
        <note>beta</note>
        <note>gamma</note>
    </root>"""
    results = _xml_to_csvs(xml, "notes")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r.get("_text") for r in rows)


def test_malformed_xml_falls_back_to_raw_bytes():
    bad = b"<root><unclosed>"
    results = _xml_to_csvs(bad, "broken")
    assert len(results) == 1
    assert results[0][0] == bad


def test_fk_column_injected_from_parent():
    xml = b"""<store id="s1">
        <product id="p1" name="Widget"/>
        <product id="p2" name="Gadget"/>
    </store>"""
    results = _xml_to_csvs(xml, "store")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r.get("store_id") == "s1" for r in rows)


# ── read_files: XML match_keys override ──────────────────────────────────────

def test_xml_derived_plans_get_text_match_key():
    # When an XML file is expanded into CSVs, _infer_type may return match_keys
    # based on the CSV sample (often ["name"] since that's the LLM fallback).
    # read_files must override match_keys to ["_text"] for every XML-derived CSV
    # because XML CSVs have no "name" column — only "_text" for the entity value.
    xml = b"""<Catalogue>
        <Product name="Widget">foo</Product>
        <Product name="Gadget">bar</Product>
        <Product name="Doohickey">baz</Product>
    </Catalogue>"""

    mock_settings = MagicMock()
    mock_settings.rdb_dsn = "mock://db"
    mock_settings.chunk_size = 500
    mock_settings.chunk_overlap = 50
    mock_settings.embed_dim = 1536

    # _infer_type would normally return ["name"] as fallback — the override must win.
    with patch("aryx.pipeline.doc_discovery.get_settings", return_value=mock_settings), \
         patch("aryx.pipeline.doc_discovery._infer_type",
               return_value={"ontology_type": "Product", "match_keys": ["name"]}):
        from aryx.pipeline.doc_discovery import read_files
        result = read_files(
            doc_paths=[],
            tabular=[(xml, "catalogue.xml")],
            broker=MagicMock(),
            context="",
        )

    for plan in result["tabular"]:
        assert plan["match_keys"] == ["_text"], (
            f"XML-derived plan '{plan['filename']}' should have match_keys=['_text'], "
            f"got {plan['match_keys']}"
        )


# ── _display_name: _text key and underscore-prefix skip ──────────────────────

def test_display_name_uses_text_key():
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Product", "_text": "TechCorp Global Industries"}
    assert falkor_dn(attrs) == "TechCorp Global Industries"
    assert oracle_dn(attrs) == "TechCorp Global Industries"


def test_display_name_skips_underscore_prefixed_keys_in_fallback():
    # When no key from _NAME_KEYS matches, the fallback loop must skip _-prefixed
    # attributes (like _element_type) to avoid returning tag names as display labels.
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Supplier", "_some_meta": "internal", "ref": "SUP-001"}
    # "ref" is in _NAME_KEYS — should be found before fallback loop runs.
    assert falkor_dn(attrs) == "SUP-001"
    assert oracle_dn(attrs) == "SUP-001"


def test_display_name_fallback_skips_underscore_no_named_key():
    # No _NAME_KEYS match; fallback loop must skip _ keys and pick the first
    # short plain-string value instead of returning the tag name.
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Supplier", "_meta": "noise", "company": "Acme Corp"}
    assert falkor_dn(attrs) == "Acme Corp"
    assert oracle_dn(attrs) == "Acme Corp"
