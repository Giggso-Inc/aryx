"""store_layout_file / catalog_prefix_from_filename -- the write side of
CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md. The read side
(OracleLayoutFileSource) is tested in tests/test_cpq_layout_visibility_
order.py, alongside LocalDirLayoutFileSource.
"""
from __future__ import annotations

import pytest

from aryx.cpq_ingestion.layout_store import (
    CpqLayoutFileTooLarge,
    _MAX_LAYOUT_FILE_BYTES,
    catalog_prefix_from_filename,
    store_layout_file,
)


class _FakeCursor:
    def __init__(self, sink: list[tuple[str, dict]]) -> None:
        self._sink = sink

    def execute(self, sql, params):
        self._sink.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur: _FakeCursor) -> None:
        self._cur = cur

    def cursor(self):
        return self._cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakePool:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, dict]] = []

    def connection(self):
        return _FakeConn(_FakeCursor(self.upserts))


def test_catalog_prefix_from_filename_uses_raw_stem_not_pascal_case():
    """NOT _stem_type's singularized/PascalCase transform -- real ingested
    catalog_prefix values are raw, filename-derived strings (e.g.
    'ApxnextCnofigdata', typo included), so this must preserve the stem
    verbatim."""
    assert catalog_prefix_from_filename("APXNext_CnofigData.txt") == "APXNext_CnofigData"
    assert catalog_prefix_from_filename("layout.json") == "layout"


def test_store_layout_file_upserts_with_derived_catalog_prefix(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)
    prefix = store_layout_file(
        b'{"status": "Active"}', "Config Layout APX Next.txt",
        workspace_id=7, dsn="fake-dsn",
    )
    assert prefix == "Config Layout APX Next"
    assert len(pool.upserts) == 1
    _sql, params = pool.upserts[0]
    assert params["workspace_id"] == 7
    assert params["catalog_prefix"] == "Config Layout APX Next"
    assert params["content_clob"] == '{"status": "Active"}'
    assert params["filename"] == "Config Layout APX Next.txt"


def test_store_layout_file_honors_explicit_catalog_prefix(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)
    prefix = store_layout_file(
        b"{}", "whatever.json",
        workspace_id=7, dsn="fake-dsn", catalog_prefix="ExplicitPrefix",
    )
    assert prefix == "ExplicitPrefix"
    assert pool.upserts[0][1]["catalog_prefix"] == "ExplicitPrefix"


def test_store_layout_file_rejects_oversized_content(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr("aryx.store.pool.get_pool", lambda dsn: pool)
    oversized = b"x" * (_MAX_LAYOUT_FILE_BYTES + 1)
    with pytest.raises(CpqLayoutFileTooLarge):
        store_layout_file(oversized, "big.txt", workspace_id=1, dsn="fake-dsn")
    assert pool.upserts == []
