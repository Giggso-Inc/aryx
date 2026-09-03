"""Unit tests for DatasourceStore.ensure() and file-ingest datasource registration."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Module-level stubs (must run before any aryx import) ─────────────────────

def _stub_psycopg() -> None:
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.Error = Exception

    class _IntegrityError(Exception):
        pass

    psycopg.IntegrityError = _IntegrityError
    psycopg.connect = MagicMock()

    psycopg_sql = types.ModuleType("psycopg.sql")
    psycopg_sql.SQL = MagicMock()
    psycopg_sql.Identifier = MagicMock()
    psycopg_sql.Literal = MagicMock()
    psycopg.sql = psycopg_sql

    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_types_json = types.ModuleType("psycopg.types.json")
    psycopg_types_json.Json = dict
    psycopg_pool = types.ModuleType("psycopg_pool")
    psycopg_pool.ConnectionPool = MagicMock()
    sys.modules["psycopg"] = psycopg
    sys.modules["psycopg.sql"] = psycopg_sql
    sys.modules["psycopg.types"] = psycopg_types
    sys.modules["psycopg.types.json"] = psycopg_types_json
    sys.modules["psycopg_pool"] = psycopg_pool


def _stub_oracledb() -> None:
    if "oracledb" in sys.modules:
        return
    mod = types.ModuleType("oracledb")
    mod.STRING = "STRING"
    mod.IntegrityError = Exception
    mod.Error = Exception
    sys.modules["oracledb"] = mod


def _stub_falkordb() -> None:
    if "falkordb" in sys.modules:
        return
    mod = types.ModuleType("falkordb")
    mod.FalkorDB = MagicMock()
    sys.modules["falkordb"] = mod


def _stub_llm_providers() -> None:
    """Stub aryx.llm_providers to avoid the module-level get_settings() call."""
    key = "aryx.llm_providers"
    if key in sys.modules:
        return
    mod = types.ModuleType(key)
    mod.anthropic_json = MagicMock()
    mod.oci_genai_json = MagicMock()
    mod.ollama_json = MagicMock()
    mod.openai_json = MagicMock()
    mod.post_json = MagicMock()
    sys.modules[key] = mod


def _stub_llm_runtime() -> None:
    """Stub aryx.llm_runtime — it calls get_settings() at module level (_cfg = ...)."""
    key = "aryx.llm_runtime"
    if key in sys.modules:
        return
    mod = types.ModuleType(key)
    mod.status = MagicMock(return_value={})
    mod.chat = MagicMock(return_value=("", 0, 0))
    mod.set_config = MagicMock()
    mod._KEY_REF = None
    mod._RuntimeSecrets = MagicMock()
    sys.modules[key] = mod


def _stub_admin_api() -> None:
    """Stub aryx.api.admin_api to prevent its cascade into llm_runtime.

    aryx.api is also stubbed as a package (with __path__ pointing at the real
    directory) so that 'from aryx.api.file_ingest_api import ...' still works —
    but aryx/api/__init__.py (which imports graph_api and its full cascade) is
    never executed. We also set aryx.api as an attribute on the aryx module so
    unittest.mock.patch can navigate to aryx.api.file_ingest_api.* targets.
    """
    import pathlib
    import aryx as _aryx_pkg
    api_dir = pathlib.Path(__file__).parent.parent / "src" / "aryx" / "api"

    if "aryx.api" not in sys.modules:
        pkg = types.ModuleType("aryx.api")
        pkg.__path__ = [str(api_dir)]
        pkg.__package__ = "aryx.api"
        pkg.__file__ = str(api_dir / "__init__.py")
        sys.modules["aryx.api"] = pkg
    _aryx_pkg.api = sys.modules["aryx.api"]

    if "aryx.api.admin_api" not in sys.modules:
        adm = types.ModuleType("aryx.api.admin_api")
        adm._local_broker = MagicMock()
        sys.modules["aryx.api.admin_api"] = adm


def _stub_get_settings() -> None:
    """Patch aryx.config.get_settings before any module-level usage.

    Several aryx modules assign module globals at import time (e.g.
    `_PER_DOC_TIMEOUT = get_settings().per_doc_timeout`). Patching
    get_settings here ensures those assignments get a MagicMock instead of
    triggering a pydantic ValidationError from the extra fields in .env.
    aryx/__init__.py is a one-liner so importing it is safe.
    """
    import aryx.config as _cfg
    _cfg.get_settings = MagicMock(return_value=MagicMock())


_stub_psycopg()
_stub_oracledb()
_stub_falkordb()
_stub_llm_providers()
_stub_llm_runtime()
_stub_admin_api()
_stub_get_settings()


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_pool(*fetchone_returns):
    """Build a mock pool whose cursor yields fetchone() values in order."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = list(fetchone_returns)

    cursor_cm = MagicMock()
    cursor_cm.__enter__ = MagicMock(return_value=cursor)
    cursor_cm.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cursor_cm

    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn)
    conn_cm.__exit__ = MagicMock(return_value=False)

    pool = MagicMock()
    pool.connection.return_value = conn_cm
    return pool


_SAMPLE_ROW = (1, 42, "file.csv", "csv", {}, "••••", "2024-01-01")


# ── B1: DatasourceStore.ensure() — three paths ───────────────────────────────

def test_ensure_returns_existing_row_without_insert():
    """Path A: SELECT finds the row — ensure() returns it, add() is never called."""
    from aryx.store.datasource_store import DatasourceStore

    store = object.__new__(DatasourceStore)
    store._pool = _make_pool(_SAMPLE_ROW)
    store.add = MagicMock()

    with patch("aryx.queries._backend", return_value="postgres"):
        result = store.ensure(42, "file.csv", "csv")

    store.add.assert_not_called()
    assert result["id"] == 1
    assert result["name"] == "file.csv"
    assert result["kind"] == "csv"


def test_ensure_inserts_when_row_not_found():
    """Path B: SELECT returns None — add() is called with empty secret."""
    from aryx.store.datasource_store import DatasourceStore

    store = object.__new__(DatasourceStore)
    store._pool = _make_pool(None)  # first SELECT finds nothing
    store.add = MagicMock(return_value={"id": 7, "name": "new.csv", "kind": "csv"})

    with patch("aryx.queries._backend", return_value="postgres"):
        result = store.ensure(42, "new.csv", "csv")

    store.add.assert_called_once_with(42, "new.csv", "csv", {}, "")
    assert result["id"] == 7


def test_ensure_recovers_from_concurrent_duplicate_insert():
    """Path C: concurrent INSERT raises unique-violation — fallback SELECT returns the row."""
    from aryx.store.datasource_store import DatasourceStore

    # First SELECT: nothing yet; fallback SELECT: row already committed by other worker
    store = object.__new__(DatasourceStore)
    store._pool = _make_pool(None, _SAMPLE_ROW)
    store.add = MagicMock(side_effect=Exception("ERROR: 23505 duplicate key value"))

    with patch("aryx.queries._backend", return_value="postgres"):
        result = store.ensure(42, "file.csv", "csv")

    assert result["id"] == 1
    assert result["name"] == "file.csv"


def test_ensure_reraises_non_duplicate_insert_errors():
    """Path C variant: non-unique errors propagate, not swallowed."""
    from aryx.store.datasource_store import DatasourceStore

    store = object.__new__(DatasourceStore)
    store._pool = _make_pool(None)
    store.add = MagicMock(side_effect=Exception("ORA-01555: snapshot too old"))

    try:
        with patch("aryx.queries._backend", return_value="postgres"):
            store.ensure(42, "file.csv", "csv")
        assert False, "expected exception not raised"  # noqa: PT015
    except Exception as exc:
        assert "ORA-01555" in str(exc)


def test_ensure_oracle_dup_code_also_recovered():
    """ORA-00001 (Oracle unique constraint) is treated the same as 23505."""
    from aryx.store.datasource_store import DatasourceStore

    store = object.__new__(DatasourceStore)
    store._pool = _make_pool(None, _SAMPLE_ROW)
    store.add = MagicMock(side_effect=Exception("ORA-00001: unique constraint violated"))

    with patch("aryx.queries._backend", return_value="postgres"):
        result = store.ensure(42, "file.csv", "csv")

    assert result["id"] == 1


# ── W5: _run_files registers a datasource for every uploaded file ─────────────

def test_run_files_registers_datasource_for_each_file():
    """ensure() is called once per item with the correct workspace, name, and kind."""
    from aryx.api.file_ingest_run import _run_files

    mock_ds_store = MagicMock()
    mock_ds_class = MagicMock(return_value=mock_ds_store)

    mock_job_store = MagicMock()
    mock_job_class = MagicMock(return_value=mock_job_store)

    settings = MagicMock()
    settings.rdb_dsn = "postgresql://test"
    settings.ingest_relate = False
    settings.csv_chunk_rows = 0
    settings.graph_url = "bolt://localhost"

    csv_item = (b"id,name\n1,Alice\n", "contacts.csv")
    pdf_item = (b"%PDF-1.4 fake", "report.pdf")

    with (
        patch("aryx.api.file_ingest_run.DatasourceStore", mock_ds_class),
        patch("aryx.api.file_ingest_run.JobStore", mock_job_class),
        patch("aryx.api.file_ingest_run.run_pipeline"),
        patch("aryx.api.file_ingest_run._local_broker", return_value=MagicMock()),
        patch("aryx.api.file_ingest_run.get_settings", return_value=settings),
        patch("aryx.api.file_ingest_run._save_tmp", return_value=MagicMock(spec=Path)),
        patch("aryx.api.file_ingest_run.ChunkStore"),
        patch("aryx.api.file_ingest_run.DocumentRouterConnector"),
    ):
        _run_files([csv_item, pdf_item], "Entity", ["name"], [], "job-xyz", workspace_id=99)

    assert mock_ds_store.ensure.call_count == 2
    mock_ds_store.ensure.assert_any_call(99, "contacts.csv", "csv")
    mock_ds_store.ensure.assert_any_call(99, "report.pdf", "docs")


def test_run_files_datasource_failure_does_not_abort_ingest():
    """A failing ensure() logs a warning but does not stop the ingest job."""
    from aryx.api.file_ingest_run import _run_files

    mock_ds_store = MagicMock()
    mock_ds_store.ensure.side_effect = Exception("DB connection lost")
    mock_ds_class = MagicMock(return_value=mock_ds_store)

    mock_job_store = MagicMock()
    mock_job_class = MagicMock(return_value=mock_job_store)

    settings = MagicMock()
    settings.rdb_dsn = "postgresql://test"
    settings.ingest_relate = False
    settings.csv_chunk_rows = 0
    settings.graph_url = "bolt://localhost"

    with (
        patch("aryx.api.file_ingest_run.DatasourceStore", mock_ds_class),
        patch("aryx.api.file_ingest_run.JobStore", mock_job_class),
        patch("aryx.api.file_ingest_run.run_pipeline"),
        patch("aryx.api.file_ingest_run._local_broker", return_value=MagicMock()),
        patch("aryx.api.file_ingest_run.get_settings", return_value=settings),
    ):
        # Must not raise even though ensure() always throws
        _run_files([(b"id\n1\n", "data.csv")], "Entity", ["name"], [], "job-1", workspace_id=1)

    # Job completed without exception; finish() was called with status=complete
    mock_job_store.finish.assert_called_once()
    call_kwargs = mock_job_store.finish.call_args
    assert call_kwargs.kwargs.get("status") == "complete" or call_kwargs.args[2] == "complete"


def test_run_files_fname_truncated_to_255_chars():
    """Filenames longer than 255 chars are silently truncated before ensure()."""
    from aryx.api.file_ingest_run import _run_files

    mock_ds_store = MagicMock()
    mock_ds_class = MagicMock(return_value=mock_ds_store)

    settings = MagicMock()
    settings.rdb_dsn = "postgresql://test"
    settings.ingest_relate = False
    settings.csv_chunk_rows = 0
    settings.graph_url = "bolt://localhost"

    long_name = "a" * 300 + ".csv"

    with (
        patch("aryx.api.file_ingest_run.DatasourceStore", mock_ds_class),
        patch("aryx.api.file_ingest_run.JobStore", return_value=MagicMock()),
        patch("aryx.api.file_ingest_run.run_pipeline"),
        patch("aryx.api.file_ingest_run._local_broker", return_value=MagicMock()),
        patch("aryx.api.file_ingest_run.get_settings", return_value=settings),
    ):
        _run_files([(b"id\n1\n", long_name)], "Entity", ["name"], [], "job-1", workspace_id=1)

    actual_name = mock_ds_store.ensure.call_args[0][1]
    assert len(actual_name) == 255
    assert actual_name == long_name[:255]
