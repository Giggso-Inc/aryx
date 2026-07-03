"""Tests for the ontology type-registry fixes in PR #42.

Covers:
  - seed_types() receives tuples, not dicts (regression guard for the
    silent data-loss bug where dict params against %s SQL wrote nothing)
  - list_browse() auto-heal: fires when type registry is empty but
    entities exist; seeds types and returns populated type_rows
  - list_browse() auto-heal: does NOT fire when entities are also empty
  - list_browse() auto-heal: exception in seed_types is caught and the
    function continues with empty type_rows (non-fatal)

Run:
    PYTHONPATH=src python -m pytest tests/test_ontology_autoheal.py -v
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level stubs — must come before any aryx imports.
# ---------------------------------------------------------------------------
for _mod in (
    "psycopg",
    "psycopg.types",
    "psycopg.types.json",
    "psycopg.rows",
    "pgvector",
    "pgvector.psycopg",
    "falkordb",
    "openai",
    "anthropic",
    "presidio_analyzer",
    "presidio_anonymizer",
    "pymupdf",
    "pymupdf4llm",
    "docx",
    "pptx",
    "PIL",
    "PIL.Image",
):
    sys.modules.setdefault(_mod, MagicMock())

_mock_cp = MagicMock()
sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=_mock_cp))

# Ensure psycopg.types.json.Json is importable as a no-op wrapper.
sys.modules["psycopg.types.json"].Json = lambda x: x


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_mock(fetchall_rows=None):
    """Return (pool, conn, cursor) mocks wired as context managers."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = fetchall_rows or []

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    return mock_pool, mock_conn, mock_cur


# ---------------------------------------------------------------------------
# seed_types — tuple regression guard
# ---------------------------------------------------------------------------

class TestSeedTypesParameterStyle:
    """seed_types() must pass tuples (not dicts) to executemany.

    The original bug: dict params with %s positional SQL → psycopg3 raises
    ProgrammingError (or silently writes nothing on older drivers). The fix
    uses tuples matching the column order in upsert_ontology_type.sql.
    """

    def test_seed_types_passes_tuples_not_dicts(self):
        """executemany must receive a list of tuples, never a list of dicts."""
        pool, _, cur = _make_db_mock()
        with patch("aryx.store.ontology_store.get_pool", return_value=pool), \
             patch("aryx.store.ontology_store.load", return_value="INSERT ..."):
            from aryx.store.ontology_store import OntologyStore
            from aryx.models import OntologyType
            store = OntologyStore("dsn", workspace_id=1)
            store.seed_types([
                OntologyType(name="Customer", attributes=["name"], status="approved", source="pipeline"),
                OntologyType(name="Vendor", attributes=[], status="proposed", source="entity-store"),
            ])

        call_args = cur.executemany.call_args
        assert call_args is not None, "executemany was not called"
        params_list = call_args[0][1]  # second positional arg = list of param rows
        assert len(params_list) == 2
        for row in params_list:
            assert isinstance(row, tuple), (
                f"expected tuple, got {type(row).__name__}: {row!r}"
            )

    def test_seed_types_tuple_column_order(self):
        """Tuple order must be (workspace_id, name, attributes, status, source)."""
        pool, _, cur = _make_db_mock()
        with patch("aryx.store.ontology_store.get_pool", return_value=pool), \
             patch("aryx.store.ontology_store.load", return_value="INSERT ..."):
            from aryx.store.ontology_store import OntologyStore
            from aryx.models import OntologyType
            store = OntologyStore("dsn", workspace_id=7)
            store.seed_types([
                OntologyType(name="Invoice", attributes=["amount"], status="approved", source="manual"),
            ])

        params_list = cur.executemany.call_args[0][1]
        ws_id, name, attrs, status, source = params_list[0]
        assert ws_id == 7
        assert name == "Invoice"
        assert status == "approved"
        assert source == "manual"

    def test_seed_types_empty_list_does_not_call_executemany(self):
        """Seeding an empty list must be a no-op (or at least not raise)."""
        pool, _, cur = _make_db_mock()
        with patch("aryx.store.ontology_store.get_pool", return_value=pool), \
             patch("aryx.store.ontology_store.load", return_value="INSERT ..."):
            from aryx.store.ontology_store import OntologyStore
            store = OntologyStore("dsn", workspace_id=1)
            store.seed_types([])  # must not raise


# ---------------------------------------------------------------------------
# list_browse — auto-heal paths
# ---------------------------------------------------------------------------

def _make_entity_row(type_name: str) -> tuple:
    """Minimal entity row: (id, ontology_type, attributes_dict)."""
    return (1, type_name, {"name": "Acme"})


def _make_type_row() -> tuple:
    """Minimal ontology type row: (name, attributes, status, source, parent_type, schema)."""
    return ("Customer", ["name"], "approved", "pipeline", None, {})


class TestListBrowseAutoHeal:
    """list_browse() auto-heal: fires when type registry empty but entities exist."""

    def _patch_browse(self, type_rows, entity_rows, rel_rows=None):
        """Context manager tuple for patching OntologyStore + EntityStore."""
        return (
            patch("aryx.api.ontology_browse.get_settings",
                  return_value=MagicMock(rdb_dsn="postgresql://x")),
            patch("aryx.api.ontology_browse.OntologyStore"),
            patch("aryx.api.ontology_browse.EntityStore"),
        )

    def test_autoheal_seeds_types_when_registry_empty_but_entities_exist(self):
        """Auto-heal fires: seed_types called with entity type names."""
        from types import SimpleNamespace
        healed = SimpleNamespace(
            name="Customer", attributes=[], status="approved",
            source="entity-store", parent_type=None, attribute_schema={},
        )
        # Give it a __dict__ so the list_browse dict-extraction path works.
        healed.__dict__.update({
            "name": "Customer", "attributes": [], "status": "approved",
            "source": "entity-store", "parent_type": None, "attribute_schema": {},
        })

        mock_onto = MagicMock()
        # First list_types() call → empty (triggers heal)
        # Second list_types() call (after seed) → one type
        mock_onto.list_types.side_effect = [
            [],
            [healed],
        ]

        mock_entity_store = MagicMock()
        # Entities exist with type "Customer"
        mock_entity_store.list_entities.return_value = iter([
            _make_entity_row("Customer"),
        ])
        mock_entity_store.list_relationships.return_value = iter([])

        with patch("aryx.api.ontology_browse.get_settings",
                   return_value=MagicMock(rdb_dsn="postgresql://x")), \
             patch("aryx.api.ontology_browse.OntologyStore", return_value=mock_onto), \
             patch("aryx.api.ontology_browse.EntityStore", return_value=mock_entity_store):
            from aryx.api.ontology_browse import list_browse
            result = list_browse(workspace_id=1)

        mock_onto.seed_types.assert_called_once()
        seeded = mock_onto.seed_types.call_args[0][0]
        assert any(t.name == "Customer" for t in seeded)

    def test_autoheal_result_has_entity_count(self):
        """After auto-heal, entity_count in the response reflects entity store data."""
        mock_onto = MagicMock()
        healed_type = MagicMock()
        healed_type.__dict__ = {"name": "Vendor", "attributes": [], "status": "approved",
                                "source": "entity-store", "parent_type": None, "attribute_schema": {}}
        mock_onto.list_types.side_effect = [[], [healed_type]]

        mock_entity_store = MagicMock()
        mock_entity_store.list_entities.return_value = iter([
            _make_entity_row("Vendor"),
            _make_entity_row("Vendor"),
        ])
        mock_entity_store.list_relationships.return_value = iter([])

        with patch("aryx.api.ontology_browse.get_settings",
                   return_value=MagicMock(rdb_dsn="postgresql://x")), \
             patch("aryx.api.ontology_browse.OntologyStore", return_value=mock_onto), \
             patch("aryx.api.ontology_browse.EntityStore", return_value=mock_entity_store):
            from aryx.api.ontology_browse import list_browse
            result = list_browse(workspace_id=1)

        assert result["entity_count"] == 2

    def test_autoheal_does_not_fire_when_entities_also_empty(self):
        """Auto-heal guard: no entities → seed_types must NOT be called."""
        mock_onto = MagicMock()
        mock_onto.list_types.return_value = []

        mock_entity_store = MagicMock()
        mock_entity_store.list_entities.return_value = iter([])
        mock_entity_store.list_relationships.return_value = iter([])

        with patch("aryx.api.ontology_browse.get_settings",
                   return_value=MagicMock(rdb_dsn="postgresql://x")), \
             patch("aryx.api.ontology_browse.OntologyStore", return_value=mock_onto), \
             patch("aryx.api.ontology_browse.EntityStore", return_value=mock_entity_store):
            from aryx.api.ontology_browse import list_browse
            result = list_browse(workspace_id=1)

        mock_onto.seed_types.assert_not_called()
        assert result["types"] == []
        assert result["entity_count"] == 0

    def test_autoheal_exception_is_caught_function_continues(self):
        """If seed_types raises, the exception is swallowed and types remains []."""
        mock_onto = MagicMock()
        mock_onto.list_types.return_value = []
        mock_onto.seed_types.side_effect = RuntimeError("DB unavailable")

        mock_entity_store = MagicMock()
        mock_entity_store.list_entities.return_value = iter([
            _make_entity_row("Product"),
        ])
        mock_entity_store.list_relationships.return_value = iter([])

        with patch("aryx.api.ontology_browse.get_settings",
                   return_value=MagicMock(rdb_dsn="postgresql://x")), \
             patch("aryx.api.ontology_browse.OntologyStore", return_value=mock_onto), \
             patch("aryx.api.ontology_browse.EntityStore", return_value=mock_entity_store), \
             patch("aryx.api.ontology_browse.logger") as mock_log:
            from aryx.api.ontology_browse import list_browse
            result = list_browse(workspace_id=1)

        assert result["types"] == []
        assert result["entity_count"] == 1
        # Warning must be emitted — the exception is non-fatal but logged
        assert mock_log.warning.called

    def test_autoheal_does_not_fire_when_types_already_present(self):
        """If type_rows is non-empty, auto-heal must not run seed_types."""
        existing_type = MagicMock()
        existing_type.__dict__ = {"name": "Customer", "attributes": ["name"],
                                  "status": "approved", "source": "pipeline",
                                  "parent_type": None, "attribute_schema": {}}
        mock_onto = MagicMock()
        mock_onto.list_types.return_value = [existing_type]

        mock_entity_store = MagicMock()
        mock_entity_store.list_entities.return_value = iter([_make_entity_row("Customer")])
        mock_entity_store.list_relationships.return_value = iter([])

        with patch("aryx.api.ontology_browse.get_settings",
                   return_value=MagicMock(rdb_dsn="postgresql://x")), \
             patch("aryx.api.ontology_browse.OntologyStore", return_value=mock_onto), \
             patch("aryx.api.ontology_browse.EntityStore", return_value=mock_entity_store):
            from aryx.api.ontology_browse import list_browse
            list_browse(workspace_id=1)

        mock_onto.seed_types.assert_not_called()
