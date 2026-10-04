"""_persist_tabular_sources must not catalog the cpq XML raw-graph preview's
synthetic "<stem>.summary.csv" counts file as a real generated asset (Raven
review finding): the parent XML is still catalogued, with assets=[].
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.pipeline.doc_discovery.doc_discovery_persist import _persist_tabular_sources


def test_preview_plan_registers_parent_with_no_assets():
    preview_plan = {
        "filename": "order.summary.csv",
        "data": b"nodes,edges\n4,3\n",
        "ontology_type": "4 nodes / 3 edges",
        "source_filename": "order.xml",
        "source_bytes": b"<Root/>",
        "cpq_raw_graph_preview": True,
    }

    with patch("aryx.pipeline.doc_discovery.doc_discovery_persist.DatasourceStore"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.upsert_xml_catalog_entry") as mock_upsert:
        _persist_tabular_sources([preview_plan], workspace_id=1, dsn="unused")

    mock_upsert.assert_called_once()
    _, kwargs = mock_upsert.call_args
    assert kwargs["source_filename"] == "order.xml"
    assert kwargs["assets"] == []


def test_real_xml_derived_plan_still_catalogs_its_asset():
    real_plan = {
        "filename": "order_Item.csv",
        "data": b"id,name\n1,a\n",
        "ontology_type": "Item",
        "source_filename": "order.xml",
        "source_bytes": b"<Root/>",
    }

    with patch("aryx.pipeline.doc_discovery.doc_discovery_persist.DatasourceStore"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.upsert_xml_catalog_entry") as mock_upsert:
        _persist_tabular_sources([real_plan], workspace_id=1, dsn="unused")

    mock_upsert.assert_called_once()
    _, kwargs = mock_upsert.call_args
    assert len(kwargs["assets"]) == 1
