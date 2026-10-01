"""store_layout_file / catalog_prefix_from_filename -- the write side of
CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md. The read side
(OracleLayoutFileSource) is tested in tests/test_cpq_layout_visibility_
order.py.
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


class _FakeDatasourceStore:
    """Records ensure() calls without touching a real pool -- store_layout_
    file's own DatasourceStore(dsn) construction would otherwise call the
    REAL aryx.store.pool.get_pool via aryx.store.datasource_store's own
    import (a different reference than layout_store.py's patched one), so
    every test in this file needs this patched too, not just get_pool."""

    calls: list[tuple] = []

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def ensure(self, workspace_id: int, name: str, kind: str) -> dict:
        type(self).calls.append((self._dsn, workspace_id, name, kind))
        return {"id": 1, "workspace_id": workspace_id, "name": name, "kind": kind}


@pytest.fixture(autouse=True)
def _patch_datasource_store(monkeypatch):
    _FakeDatasourceStore.calls = []
    monkeypatch.setattr(
        "aryx.cpq_ingestion.layout_store.DatasourceStore", _FakeDatasourceStore,
    )
    yield


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


def test_store_layout_file_invalidates_process_lifetime_layout_caches(monkeypatch):
    """A re-upload replacing an already-queried (workspace_id, catalog_prefix)
    pair must drop that key from engine_caches.py's layout caches --
    otherwise the OLD (or None) cached value would keep being served for
    the rest of this process's lifetime, since those caches have no TTL."""
    from aryx.cpq import engine_caches

    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)

    key = (7, "ExplicitPrefix")
    engine_caches._LAYOUT_COMPONENTS_CACHE[key] = [{"stale": True}]
    engine_caches._LAYOUT_DISPLAY_ORDER_CACHE[key] = {"stale": 1}
    engine_caches._LAYOUT_FULL_ORDER_CACHE[key] = {"stale": 1}
    try:
        store_layout_file(
            b"{}", "whatever.json",
            workspace_id=7, dsn="fake-dsn", catalog_prefix="ExplicitPrefix",
        )
        assert key not in engine_caches._LAYOUT_COMPONENTS_CACHE
        assert key not in engine_caches._LAYOUT_DISPLAY_ORDER_CACHE
        assert key not in engine_caches._LAYOUT_FULL_ORDER_CACHE
    finally:
        engine_caches._LAYOUT_COMPONENTS_CACHE.pop(key, None)
        engine_caches._LAYOUT_DISPLAY_ORDER_CACHE.pop(key, None)
        engine_caches._LAYOUT_FULL_ORDER_CACHE.pop(key, None)


def test_store_layout_file_invalidation_does_not_disturb_other_keys(monkeypatch):
    from aryx.cpq import engine_caches

    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)

    other_key = (99, "Unrelated")
    engine_caches._LAYOUT_COMPONENTS_CACHE[other_key] = [{"keep": True}]
    try:
        store_layout_file(
            b"{}", "whatever.json",
            workspace_id=7, dsn="fake-dsn", catalog_prefix="ExplicitPrefix",
        )
        assert engine_caches._LAYOUT_COMPONENTS_CACHE[other_key] == [{"keep": True}]
    finally:
        engine_caches._LAYOUT_COMPONENTS_CACHE.pop(other_key, None)


def test_store_layout_file_registers_datasource_so_it_shows_on_data_sources_page(monkeypatch):
    """Previously only written to aryx_cpq_layout_file, which the Data >
    Sources page (built from DatasourceStore.list()) never reads -- an
    uploaded layout file was invisible there. ensure() must be called
    with kind="cpq_layout" so source_catalog_meta._display_kind() renders
    it as "CPQ Layout File" on that page."""
    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)

    store_layout_file(
        b'{"status": "Active"}', "Config Layout APX Next.txt",
        workspace_id=7, dsn="fake-dsn",
    )

    assert _FakeDatasourceStore.calls == [
        ("fake-dsn", 7, "Config Layout APX Next.txt", "cpq_layout"),
    ]


def test_store_layout_file_datasource_ensure_failure_does_not_fail_the_store(monkeypatch):
    """Best-effort: a datasource-registration failure must never undo or
    fail the layout storage that already succeeded."""
    pool = _FakePool()
    monkeypatch.setattr("aryx.cpq_ingestion.layout_store.get_pool", lambda dsn: pool)

    class _BrokenDatasourceStore:
        def __init__(self, dsn: str) -> None:
            pass

        def ensure(self, *a, **k):
            raise RuntimeError("datasource backend unavailable")

    monkeypatch.setattr(
        "aryx.cpq_ingestion.layout_store.DatasourceStore", _BrokenDatasourceStore,
    )

    prefix = store_layout_file(
        b"{}", "whatever.json", workspace_id=7, dsn="fake-dsn",
    )
    assert prefix == "whatever"
    assert len(pool.upserts) == 1
