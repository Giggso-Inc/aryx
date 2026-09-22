"""Tests for the 2026-09-16 fix: xml_catalog_config/xml_asset_record/
xlsx_catalog_config/xlsx_asset_record must never embed content over
Postgres's single-jsonb-string limit (268,435,455 bytes) -- real incident:
a confirm job crashed with psycopg.errors.ProgramLimitExceeded ("string
too long to represent as jsonb string") persisting the XML catalog entry
for a large upload, via DatasourceStore.add()'s Json(config) write.

_safe_content_fields() caps inline content at _MAX_INLINE_CONTENT_BYTES,
omitting content_b64 (None) for anything larger instead of raising, and
setting an explicit content_omitted_oversized=True marker -- every read
site already has a fallback for a missing content_b64 (see
TestMissingContentB64FallsBackGracefully below), and the marker itself
is what tests/find_legacy_xml_row's PR #334 review fix depends on (see
TestFindLegacyXmlRowIsNotFooledByOversizedContent).
"""
from __future__ import annotations

import base64

from aryx.source.source_catalog import (
    _MAX_INLINE_CONTENT_BYTES,
    _safe_content_fields,
    find_legacy_xml_row,
    xlsx_asset_record,
    xlsx_catalog_config,
    xml_asset_record,
    xml_catalog_config,
    xml_download_payload,
)


class TestSafeContentFields:
    def test_small_content_is_encoded_normally_with_no_marker(self):
        raw = b"<root><item/></root>"
        fields = _safe_content_fields(raw, source_filename="x.xml")
        assert fields == {"content_b64": base64.b64encode(raw).decode("ascii")}
        assert "content_omitted_oversized" not in fields

    def test_content_over_the_cap_is_omitted_with_marker(self):
        raw = b"x" * (_MAX_INLINE_CONTENT_BYTES + 1)
        fields = _safe_content_fields(raw, source_filename="big.xml")
        assert fields == {"content_b64": None, "content_omitted_oversized": True}

    def test_content_exactly_at_the_cap_is_still_encoded(self):
        raw = b"x" * _MAX_INLINE_CONTENT_BYTES
        fields = _safe_content_fields(raw, source_filename="edge.xml")
        assert fields["content_b64"] is not None
        assert base64.b64decode(fields["content_b64"]) == raw
        assert "content_omitted_oversized" not in fields

    def test_omission_is_logged_with_the_filename_and_size(self, caplog):
        import logging
        raw = b"x" * (_MAX_INLINE_CONTENT_BYTES + 500)
        with caplog.at_level(logging.WARNING):
            _safe_content_fields(raw, source_filename="huge_catalog.xml")
        assert any(
            "huge_catalog.xml" in r.message and "omitting content_b64" in r.message
            for r in caplog.records
        )


class TestCatalogConfigBuildersNeverEmbedOversizedContent:
    def test_xml_catalog_config_omits_content_b64_for_oversized_file(self):
        oversized = b"x" * (_MAX_INLINE_CONTENT_BYTES + 1)
        config = xml_catalog_config("big.xml", oversized, assets=[])
        meta = config["source_catalog"]["xml"]
        assert meta["content_b64"] is None
        assert meta["content_omitted_oversized"] is True
        # The metadata that matters for the Data tab must survive intact.
        assert meta["source_filename"] == "big.xml"

    def test_xml_catalog_config_keeps_content_b64_for_normal_file(self):
        small = b"<root/>"
        config = xml_catalog_config("small.xml", small, assets=[])
        meta = config["source_catalog"]["xml"]
        assert meta["content_b64"] is not None
        assert base64.b64decode(meta["content_b64"]) == small
        assert "content_omitted_oversized" not in meta

    def test_xlsx_catalog_config_omits_content_b64_for_oversized_file(self):
        oversized = b"x" * (_MAX_INLINE_CONTENT_BYTES + 1)
        config = xlsx_catalog_config("big.xlsx", oversized, assets=[])
        meta = config["source_catalog"]["xlsx"]
        assert meta["content_b64"] is None
        assert meta["content_omitted_oversized"] is True

    def test_xml_asset_record_omits_content_b64_for_oversized_asset(self):
        oversized = b"x" * (_MAX_INLINE_CONTENT_BYTES + 1)
        asset = xml_asset_record(
            filename="huge_table.csv", dataset="huge_table",
            ontology_type="HugeTable", content_bytes=oversized,
        )
        assert asset["content_b64"] is None
        assert asset["content_omitted_oversized"] is True
        assert asset["filename"] == "huge_table.csv"  # metadata unaffected

    def test_xlsx_asset_record_omits_content_b64_for_oversized_asset(self):
        oversized = b"x" * (_MAX_INLINE_CONTENT_BYTES + 1)
        asset = xlsx_asset_record(
            filename="huge_sheet.csv", dataset="huge_sheet",
            ontology_type="HugeSheet", content_bytes=oversized,
        )
        assert asset["content_b64"] is None
        assert asset["content_omitted_oversized"] is True


class TestMissingContentB64FallsBackGracefully:
    """The whole point of omitting (not erroring on) oversized content --
    every read site already tolerates a missing content_b64."""

    def test_xml_download_falls_back_to_manifest_when_top_level_content_missing(self):
        row = {
            "id": 1, "workspace_id": 1, "name": "big.xml", "kind": "xml",
            "config": {
                "source_catalog": {
                    "xml": {
                        "source_filename": "big.xml",
                        "content_type": "application/xml",
                        "content_b64": None,  # omitted by the size guard
                        "content_omitted_oversized": True,
                        "generated_assets": [
                            {"asset_key": "big_Table.csv", "filename": "big_Table.csv",
                             "dataset": "big_Table", "ontology_type": "Table",
                             "content_b64": "YSxiCjEsMg==", "content_type": "text/csv"},
                        ],
                        "deleted": False,
                    },
                },
            },
            "secret_mask": "", "created_at": None,
        }
        result = xml_download_payload(row)
        assert result is not None
        content, filename, content_type = result
        assert filename == "big.xml"
        assert content_type == "application/xml"
        # Falls back to the synthetic manifest, not a crash or None.
        assert b"aryxXmlSource" in content

    def test_xml_download_asset_falls_back_when_asset_content_missing(self):
        row = {
            "id": 1, "workspace_id": 1, "name": "big.xml", "kind": "xml",
            "config": {
                "source_catalog": {
                    "xml": {
                        "source_filename": "big.xml", "content_type": "application/xml",
                        "content_b64": "PHJvb3QvPg==",
                        "generated_assets": [
                            {"asset_key": "big_Table.csv", "filename": "big_Table.csv",
                             "dataset": "big_Table", "ontology_type": "Table",
                             "content_b64": None, "content_omitted_oversized": True,
                             "content_type": "text/csv"},
                        ],
                        "deleted": False,
                    },
                },
            },
            "secret_mask": "", "created_at": None,
        }
        # No cached bytes and no payload_rows_by_dataset supplied -> the
        # documented "can't reconstruct" case, must return None, not raise.
        result = xml_download_payload(row, asset_key="big_Table.csv")
        assert result is None


class TestFindLegacyXmlRowIsNotFooledByOversizedContent:
    """PR #334 review finding (C1): before content_omitted_oversized
    existed, find_legacy_xml_row's fallback heuristic (no content_b64 +
    assets + matching filename) could not tell a genuine pre-migration
    legacy placeholder row apart from a real, current upload that was
    simply too large to inline -- risking upsert_legacy_xml_catalog_entry
    silently overwriting the real row's config with synthetic legacy data.
    """

    def test_oversized_real_row_is_not_matched_as_legacy(self):
        # A real OrdersExport.xml upload, too large to inline, whose
        # generated assets happen to share the "OrdersExport" stem --
        # exactly the collision the review flagged as realistic.
        real_oversized_row = {
            "id": 42, "workspace_id": 1, "name": "OrdersExport.xml", "kind": "xml",
            "config": {
                "source_catalog": {
                    "xml": {
                        "source_filename": "OrdersExport.xml",
                        "content_type": "application/xml",
                        "content_b64": None,
                        "content_omitted_oversized": True,
                        "generated_assets": [
                            {"asset_key": "OrdersExport_Orders.csv",
                             "filename": "OrdersExport_Orders.csv",
                             "dataset": "OrdersExport_Orders", "ontology_type": "Order"},
                        ],
                        "deleted": False,
                    },
                },
            },
            "secret_mask": "", "created_at": None,
        }
        assert find_legacy_xml_row([real_oversized_row], "OrdersExport") is None

    def test_genuine_legacy_row_without_the_marker_is_still_matched(self):
        # A real pre-migration legacy row: no legacy_prefix key (older
        # shape), no content_b64, no content_omitted_oversized -- must
        # still be found, since that's find_legacy_xml_row's actual job.
        legacy_row = {
            "id": 7, "workspace_id": 1, "name": "OrdersExport.xml", "kind": "xml",
            "config": {
                "source_catalog": {
                    "xml": {
                        "source_filename": "OrdersExport.xml",
                        "content_type": "application/xml",
                        "generated_assets": [
                            {"asset_key": "OrdersExport_Orders.csv",
                             "filename": "OrdersExport_Orders.csv",
                             "dataset": "OrdersExport_Orders", "ontology_type": "Order"},
                        ],
                        "deleted": False,
                    },
                },
            },
            "secret_mask": "", "created_at": None,
        }
        assert find_legacy_xml_row([legacy_row], "OrdersExport") is legacy_row

    def test_row_with_explicit_legacy_prefix_is_always_matched(self):
        row = {
            "id": 9, "workspace_id": 1, "name": "OrdersExport.xml", "kind": "xml",
            "config": {
                "source_catalog": {
                    "xml": {
                        "source_filename": "OrdersExport.xml",
                        "legacy_prefix": "OrdersExport",
                        "generated_assets": [],
                        "deleted": False,
                    },
                },
            },
            "secret_mask": "", "created_at": None,
        }
        assert find_legacy_xml_row([row], "OrdersExport") is row
