"""Tests for XML-aware source catalog shaping."""
from __future__ import annotations

from aryx.source_catalog import (
    build_source_catalog,
    build_source_detail,
    find_legacy_xml_row,
    legacy_xml_row,
    restore_generic_source_entry,
    xml_download_payload,
)


def _xml_row(datasource_id: int = 11) -> dict:
    return {
        "id": datasource_id,
        "workspace_id": 1,
        "name": "Corporate_Data.xml",
        "kind": "xml",
        "config": {
            "source_catalog": {
                "xml": {
                    "source_filename": "Corporate_Data.xml",
                    "content_type": "application/xml",
                    "content_b64": "PHJvb3QvPg==",
                    "generated_assets": [
                        {
                            "asset_key": "Corporate_Data_Employees.csv",
                            "filename": "Corporate_Data_Employees.csv",
                            "dataset": "Corporate_Data_Employees",
                            "ontology_type": "Employee",
                            "content_b64": "YSxiCjEsMg==",
                            "content_type": "text/csv",
                        },
                        {
                            "asset_key": "Corporate_Data_Departments.csv",
                            "filename": "Corporate_Data_Departments.csv",
                            "dataset": "Corporate_Data_Departments",
                            "ontology_type": "Department",
                            "content_b64": "YSxiCjMsNA==",
                            "content_type": "text/csv",
                        },
                    ],
                },
            },
        },
        "secret_mask": "",
        "created_at": None,
    }


def test_build_source_catalog_hides_generated_csv_assets_under_xml_parent() -> None:
    datasources = [_xml_row()]
    provenance = [
        (1, "csv", "Corporate_Data_Employees", "1"),
        (2, "csv", "Corporate_Data_Employees", "2"),
        (3, "csv", "Corporate_Data_Departments", "10"),
        (4, "rest", "hr_api", "x"),
    ]

    rows = build_source_catalog(datasources, provenance)

    assert [row["name"] for row in rows] == ["Corporate_Data.xml", "rest.hr_api"]
    assert rows[0]["generatedAssetCount"] == 2
    assert rows[0]["record_count"] == 3
    assert rows[0]["actions"]["download"] is True
    assert rows[0]["actions"]["delete"] is True


def test_build_source_catalog_groups_legacy_xml_like_csv_fragments() -> None:
    rows = build_source_catalog(
        datasources=[],
        provenance=[
            (1, "csv", "ontology_domain", "1"),
            (2, "csv", "ontology_range", "2"),
            (3, "csv", "ontology_Class", "3"),
        ],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == "ontology.xml"
    assert rows[0]["isXmlParent"] is True
    assert rows[0]["generatedAssetCount"] == 3
    assert rows[0]["actions"]["download"] is True
    assert rows[0]["actions"]["delete"] is True


def test_build_source_catalog_leaves_single_csv_dataset_visible() -> None:
    rows = build_source_catalog(
        datasources=[],
        provenance=[(1, "csv", "customers", "1")],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == "csv.customers"
    assert rows[0]["isXmlParent"] is False
    assert rows[0]["actions"]["view"] is True
    assert rows[0]["actions"]["download"] is True
    assert rows[0]["actions"]["delete"] is True


def test_build_source_detail_returns_assets_with_preview_rows() -> None:
    detail = build_source_detail(
        source_key="xml:11",
        datasources=[_xml_row()],
        provenance=[
            (1, "csv", "Corporate_Data_Employees", "1"),
            (2, "csv", "Corporate_Data_Employees", "2"),
            (3, "csv", "Corporate_Data_Departments", "10"),
        ],
    )

    assert detail is not None
    assert detail["name"] == "Corporate_Data.xml"
    assert detail["primary"]["actions"]["download"] is True
    assert detail["assets"][0]["filename"] == "Corporate_Data_Employees.csv"
    assert detail["assets"][0]["record_count"] == 2
    assert detail["assets"][0]["preview_rows"][0]["a"] == "1"


def test_build_source_detail_returns_legacy_xml_with_actions_and_preview() -> None:
    detail = build_source_detail(
        source_key="legacy-xml:ontology",
        datasources=[],
        provenance=[
            (1, "csv", "ontology_domain", "1"),
            (2, "csv", "ontology_range", "2"),
        ],
        dataset_payloads={
            "ontology_domain": [{"name": "Domain A"}],
            "ontology_range": [{"name": "Range B"}],
        },
    )

    assert detail is not None
    assert detail["name"] == "ontology.xml"
    assert detail["primary"]["actions"]["download"] is True
    assert detail["assets"][0]["actions"]["delete"] is True
    assert detail["assets"][0]["preview_rows"][0]["name"] == "Domain A"


def test_legacy_xml_download_payload_builds_manifest_and_csv_bytes() -> None:
    row = legacy_xml_row("ontology", ["ontology_domain"], workspace_id=1)

    manifest = xml_download_payload(
        row,
        counts={( "csv", "ontology_domain"): 4},
    )
    assert manifest is not None
    assert manifest[1] == "ontology.xml"
    assert b"<aryxXmlSource" in manifest[0]

    asset_payload = xml_download_payload(
        row,
        asset_key="ontology_domain",
        payload_rows_by_dataset={"ontology_domain": [{"name": "A", "kind": "domain"}]},
    )
    assert asset_payload is not None
    assert asset_payload[1] == "ontology_domain.csv"
    assert b"name,kind" in asset_payload[0]


def test_find_legacy_xml_row_ignores_empty_xml_row_without_assets() -> None:
    row = {
        "id": 99,
        "workspace_id": 1,
        "name": "ontology.xml",
        "kind": "xml",
        "config": {},
    }

    assert find_legacy_xml_row([row], "ontology") is None


def test_restore_generic_source_entry_unhides_reingested_source() -> None:
    row = {
        "id": 7,
        "workspace_id": 1,
        "name": "csv.suppliers",
        "kind": "source_catalog",
        "config": {
            "source_catalog": {
                "generic": {
                    "source_system": "csv",
                    "source_dataset": "suppliers",
                    "is_active": False,
                    "deleted": True,
                },
            },
        },
    }

    class _FakeStore:
        def __init__(self, item: dict) -> None:
            self.item = item

        def list(self, workspace_id: int) -> list[dict]:
            return [self.item]

        def update(
            self,
            datasource_id: int,
            *,
            name: str,
            kind: str,
            config: dict,
            secret: str | None = None,
        ) -> dict:
            assert datasource_id == 7
            self.item["name"] = name
            self.item["kind"] = kind
            self.item["config"] = config
            return self.item

    store = _FakeStore(row)

    restore_generic_source_entry(
        store,
        workspace_id=1,
        source_system="csv",
        source_dataset="suppliers",
    )

    rows = build_source_catalog(
        datasources=[row],
        provenance=[(1, "csv", "suppliers", "1")],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == "csv.suppliers"


def test_build_source_catalog_prefers_active_generic_row_over_stale_deleted_duplicate() -> None:
    datasources = [
        {
            "id": 1,
            "workspace_id": 1,
            "name": "csv.suppliers",
            "kind": "source_catalog",
            "config": {
                "source_catalog": {
                    "generic": {
                        "source_system": "csv",
                        "source_dataset": "suppliers",
                        "is_active": False,
                        "deleted": True,
                    },
                },
            },
        },
        {
            "id": 2,
            "workspace_id": 1,
            "name": "csv.suppliers",
            "kind": "source_catalog",
            "config": {
                "source_catalog": {
                    "generic": {
                        "source_system": "csv",
                        "source_dataset": "suppliers",
                        "is_active": True,
                        "deleted": False,
                    },
                },
            },
        },
    ]

    rows = build_source_catalog(
        datasources=datasources,
        provenance=[(1, "csv", "suppliers", "1")],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == "csv.suppliers"


def test_build_source_catalog_ignores_legacy_generic_tombstone_without_active_state() -> None:
    rows = build_source_catalog(
        datasources=[
            {
                "id": 1,
                "workspace_id": 1,
                "name": "csv.suppliers",
                "kind": "source_catalog",
                "config": {
                    "source_catalog": {
                        "generic": {
                            "source_system": "csv",
                            "source_dataset": "suppliers",
                            "deleted": True,
                        },
                    },
                },
            },
        ],
        provenance=[(1, "csv", "suppliers", "1")],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == "csv.suppliers"
