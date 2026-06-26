"""Tests for _xml_to_csvs in pipeline.doc_discovery."""
import csv
import io

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
