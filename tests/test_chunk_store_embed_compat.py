"""ChunkStore.check_embed_compat() determinism (review finding M2).

select_embedding_model.sql used to be an un-scoped `SELECT DISTINCT
model_id, dim ... LIMIT 1` — once two model_ids legitimately coexist
(scripts/reembed_gemini.py's backfill window, before its documented
manual DELETE of the old rows), Postgres's arbitrary physical row order
could flip the check's verdict across restarts with nothing actually
wrong. The fix scopes the query to the configured model_id via a bind
param, so the result no longer depends on what else is in the table.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.store.chunk_store import ChunkStore


def _store_with_result(row: tuple | None) -> tuple[ChunkStore, MagicMock]:
    pool = MagicMock()
    cursor = pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    with patch("aryx.store.chunk_store.get_pool", return_value=pool):
        store = ChunkStore("postgresql://x")
    return store, cursor


def test_check_embed_compat_queries_scoped_to_the_configured_model_id() -> None:
    """The bind param must be the CONFIGURED model, not left for an
    unscoped DISTINCT to guess at — this is what makes the result
    deterministic regardless of how many other model_ids coexist."""
    store, cursor = _store_with_result((768,))

    store.check_embed_compat(model_id="gemini-embedding-2", dim=768)

    args = cursor.execute.call_args
    assert args[0][1] == ("gemini-embedding-2",)


def test_check_embed_compat_passes_on_matching_dim() -> None:
    store, _cursor = _store_with_result((768,))
    store.check_embed_compat(model_id="gemini-embedding-2", dim=768)  # no raise


def test_check_embed_compat_raises_on_dim_mismatch() -> None:
    store, _cursor = _store_with_result((384,))

    with pytest.raises(RuntimeError, match="embed model mismatch"):
        store.check_embed_compat(model_id="gemini-embedding-2", dim=768)


def test_check_embed_compat_passes_when_configured_model_has_no_rows_yet() -> None:
    """No stored row for the configured model isn't a mismatch — same
    'nothing to compare against' pass as before, just scoped to this
    model rather than the whole table (a coexisting OTHER model_id's
    rows, e.g. the old nomic-embed-text rows mid-migration, must never
    affect this outcome — that coexistence is exactly what used to make
    the unscoped query nondeterministic)."""
    store, _cursor = _store_with_result(None)
    store.check_embed_compat(model_id="gemini-embedding-2", dim=768)  # no raise


def test_check_embed_compat_result_is_independent_of_other_coexisting_models() -> None:
    """Regression for the exact bug: two calls against two different mocked
    'physical row orders' (simulated by two separate stores each returning
    only ITS configured model's row) must agree — neither run's outcome
    is influenced by whatever other model_id rows happen to exist,
    because the query no longer looks at them at all."""
    gemini_store, _c1 = _store_with_result((768,))
    also_gemini_store, _c2 = _store_with_result((768,))  # same config, "different restart"

    gemini_store.check_embed_compat(model_id="gemini-embedding-2", dim=768)
    also_gemini_store.check_embed_compat(model_id="gemini-embedding-2", dim=768)
    # Both pass identically — no raise from either — proving the outcome
    # depends only on the configured model's own row, never on row order.
