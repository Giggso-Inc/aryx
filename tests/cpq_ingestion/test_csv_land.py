"""land_csv_directly -- direct CSV -> Postgres landing, no knowledge graph.

CsvConnector/discover/PostgresStore are mocked (real DB behavior is covered
by discover()'s and PostgresStore's own test suites); this only verifies
land_csv_directly wires them correctly and never touches resolve/relate/
project.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq_ingestion.csv_land import SOURCE_SYSTEM, land_csv_directly

CSV_BYTES = b"id,name\n1,Widget\n2,Gadget\n"


def _mock_store(rows_landed: int = 2) -> MagicMock:
    store = MagicMock()
    store.count_landed.return_value = rows_landed
    return store


def test_lands_via_discover_and_returns_run_id_and_row_count():
    mock_store = _mock_store(rows_landed=2)
    with patch("aryx.cpq_ingestion.csv_land.PostgresStore", return_value=mock_store), \
         patch("aryx.cpq_ingestion.csv_land.discover", return_value=42) as mock_discover:
        result = land_csv_directly(CSV_BYTES, "catalog", workspace_id=879, dsn="postgresql://x")

    mock_discover.assert_called_once()
    assert result == {"run_id": 42, "source_key": "catalog", "rows_landed": 2}


def test_uses_a_csv_connector_built_from_the_given_bytes():
    mock_store = _mock_store()
    with patch("aryx.cpq_ingestion.csv_land.PostgresStore", return_value=mock_store), \
         patch("aryx.cpq_ingestion.csv_land.discover", return_value=1) as mock_discover, \
         patch("aryx.cpq_ingestion.csv_land.CsvConnector") as mock_connector_cls:
        land_csv_directly(CSV_BYTES, "catalog", workspace_id=1, dsn="postgresql://x")

    mock_connector_cls.assert_called_once_with(CSV_BYTES, system=SOURCE_SYSTEM, dataset="catalog")
    connector_instance = mock_connector_cls.return_value
    args, _ = mock_discover.call_args
    assert args[0] is connector_instance


def test_opens_postgres_store_with_given_dsn_and_workspace_id():
    mock_store = _mock_store()
    with patch("aryx.cpq_ingestion.csv_land.PostgresStore", return_value=mock_store) as mock_store_cls, \
         patch("aryx.cpq_ingestion.csv_land.discover", return_value=1):
        land_csv_directly(CSV_BYTES, "catalog", workspace_id=879, dsn="postgresql://x")

    mock_store_cls.assert_called_once_with("postgresql://x", 879)


def test_discover_called_with_source_system_and_stem_as_dataset():
    mock_store = _mock_store()
    with patch("aryx.cpq_ingestion.csv_land.PostgresStore", return_value=mock_store), \
         patch("aryx.cpq_ingestion.csv_land.discover", return_value=1) as mock_discover:
        land_csv_directly(CSV_BYTES, "my_catalog", workspace_id=1, dsn="postgresql://x")

    args, _ = mock_discover.call_args
    assert args[2] == SOURCE_SYSTEM
    assert args[3] == "my_catalog"


def test_store_is_always_closed_even_if_discover_raises():
    mock_store = _mock_store()
    with patch("aryx.cpq_ingestion.csv_land.PostgresStore", return_value=mock_store), \
         patch("aryx.cpq_ingestion.csv_land.discover", side_effect=RuntimeError("boom")):
        try:
            land_csv_directly(CSV_BYTES, "catalog", workspace_id=1, dsn="postgresql://x")
        except RuntimeError:
            pass

    mock_store.close.assert_called_once()


def test_never_imports_resolve_relate_or_project_machinery():
    """Structural guard: this module has no dependency on resolve/relate/
    graph-projection machinery at all -- checked against the module's
    actual bound names (its __dict__ after import), not raw file text,
    so a mention in a comment/docstring can't produce a false positive."""
    import aryx.cpq_ingestion.csv_land as module
    forbidden_names = {"resolve_run", "run_pipeline", "project_auto", "EntityStore", "RawGraphConnector"}
    bound_names = set(vars(module))
    assert not (forbidden_names & bound_names), (
        f"csv_land.py must not import: {forbidden_names & bound_names}"
    )
