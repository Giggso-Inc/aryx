"""Tests for the 2026-09-22 fix: Oracle's native JSON column type has a
hard ~32MB whole-object cap (ORA-40604/JZN-00092) -- distinct from and
much smaller than Postgres's jsonb per-scalar-string limit that
_MAX_INLINE_CONTENT_BYTES already guards. A 32-entity-type XML upload's
config_json write failed live on the Oracle backend because 32 individually
small generated-asset content_b64 fields summed past 32MB in one document.

apply_oracle_json_budget sums every embedded content_b64 in one catalog
config and, only on the Oracle backend, strips the largest entries first
until the total fits, reusing the existing content_omitted_oversized
fallback contract.
"""
from __future__ import annotations

import base64
from unittest.mock import patch

from aryx.source.source_catalog import xml_catalog_config, xml_asset_record
from aryx.source.source_catalog_oracle_budget import (
    _MAX_ORACLE_JSON_OBJECT_BYTES,
    apply_oracle_json_budget,
)


def _asset(filename: str, size: int) -> dict:
    return xml_asset_record(
        filename=filename, dataset=filename.rsplit(".", 1)[0],
        ontology_type="Table", content_bytes=b"x" * size,
    )


class TestNoOpOffOracle:
    def test_postgres_backend_leaves_oversized_config_untouched(self):
        assets = [_asset(f"a{i}.csv", 2 * 1024 * 1024) for i in range(20)]
        config = xml_catalog_config("big.xml", b"<root/>", assets)
        with patch("aryx.config.get_settings") as mock_cfg:
            mock_cfg.return_value.effective_db_backend.return_value = "postgres"
            result = apply_oracle_json_budget(config)
        for asset in result["source_catalog"]["xml"]["generated_assets"]:
            assert asset["content_b64"] is not None


class TestUnderBudgetIsUntouched:
    def test_small_config_keeps_all_content_on_oracle(self):
        assets = [_asset("a.csv", 1024), _asset("b.csv", 1024)]
        config = xml_catalog_config("small.xml", b"<root/>", assets)
        with patch("aryx.config.get_settings") as mock_cfg:
            mock_cfg.return_value.effective_db_backend.return_value = "oci"
            result = apply_oracle_json_budget(config)
        for asset in result["source_catalog"]["xml"]["generated_assets"]:
            assert asset["content_b64"] is not None
            assert "content_omitted_oversized" not in asset


class TestOverBudgetTrimsLargestFirst:
    def test_combined_assets_over_cap_are_trimmed_until_under_budget(self):
        # 20 assets x 2MB base64 content each ~= 40MB > 28MB budget.
        assets = [_asset(f"a{i}.csv", 2 * 1024 * 1024) for i in range(20)]
        config = xml_catalog_config("big.xml", b"<root/>", assets)
        with patch("aryx.config.get_settings") as mock_cfg:
            mock_cfg.return_value.effective_db_backend.return_value = "oci"
            result = apply_oracle_json_budget(config)

        result_assets = result["source_catalog"]["xml"]["generated_assets"]
        remaining_total = sum(
            len(a["content_b64"]) for a in result_assets if a.get("content_b64")
        )
        assert remaining_total <= _MAX_ORACLE_JSON_OBJECT_BYTES

        stripped = [a for a in result_assets if a["content_b64"] is None]
        kept = [a for a in result_assets if a["content_b64"] is not None]
        assert stripped, "expected at least one asset to be trimmed"
        for asset in stripped:
            assert asset["content_omitted_oversized"] is True
            # Metadata must survive even when content is stripped.
            assert asset["filename"]

        # All trimmed assets are same size here, so this just confirms
        # kept+stripped partition covers everything with no data loss
        # beyond content_b64/content_omitted_oversized.
        assert len(stripped) + len(kept) == len(result_assets) == 20

    def test_main_file_content_is_only_stripped_if_still_over_budget(self):
        # One huge main file, no assets -- must still be trimmed alone.
        oversized_main = b"x" * (30 * 1024 * 1024)
        config = xml_catalog_config("huge.xml", oversized_main, assets=[])
        with patch("aryx.config.get_settings") as mock_cfg:
            mock_cfg.return_value.effective_db_backend.return_value = "oci"
            result = apply_oracle_json_budget(config)
        meta = result["source_catalog"]["xml"]
        assert meta["content_b64"] is None
        assert meta["content_omitted_oversized"] is True
        assert meta["source_filename"] == "huge.xml"

    def test_result_is_json_serializable_and_within_budget_bytes(self):
        import json
        assets = [_asset(f"a{i}.csv", 3 * 1024 * 1024) for i in range(15)]
        config = xml_catalog_config("big.xml", b"<root/>", assets)
        with patch("aryx.config.get_settings") as mock_cfg:
            mock_cfg.return_value.effective_db_backend.return_value = "oci"
            result = apply_oracle_json_budget(config)
        serialized = json.dumps(result)
        assert len(serialized.encode("utf-8")) < 32 * 1024 * 1024
