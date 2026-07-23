"""resolve_run() wiring: review-queue + survivorship-policy activation.

Verifies the previously-dead paths (StoreReviewSink, SurvivorshipPolicy) are
actually instantiated and used, and that DB/lookup failures degrade safely
rather than aborting the run.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolve_entities import resolve_run


def _store_with_records(records: list[ResolutionRecord]) -> MagicMock:
    store = MagicMock()
    store.landed_records.return_value = records
    store.save.return_value = 0
    return store


def test_review_band_pair_reaches_adjudication_store() -> None:
    """A review-band pair should flow through StoreReviewSink into AdjudicationStore.enqueue."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={"name": "Acme Corp"}),
        ResolutionRecord(record_id=2, text="Acme Corporation", payload={"name": "Acme Corporation"}),
    ]
    store = _store_with_records(records)
    broker = MagicMock()
    broker.embed.return_value = []  # force string-only scoring

    mock_adj_store = MagicMock()
    mock_ws_store = MagicMock()
    mock_ws_store.get_survivorship.return_value = {}

    with patch("aryx.resolve_entities.AdjudicationStore", return_value=mock_adj_store), \
         patch("aryx.resolve_entities.make_workspace_store", return_value=mock_ws_store), \
         patch("aryx.resolution.run.get_settings") as mock_settings:
        mock_settings.return_value.er_auto_merge = 1.0
        mock_settings.return_value.er_adjudicate = 1.0
        mock_settings.return_value.er_review = 0.0  # everything scoring > 0 goes to review band
        mock_settings.return_value.embed_batch_size = 50
        mock_settings.return_value.max_pairs_per_block = 500

        resolve_run(run_id=99, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=5)

    mock_adj_store.enqueue.assert_called()
    call_args = mock_adj_store.enqueue.call_args
    assert call_args[0][0] == 99  # run_id passed through to the sink


def test_survivorship_defaults_to_most_complete_when_unconfigured() -> None:
    """No workspace survivorship config -> policy defaults to most_complete."""
    store = _store_with_records([])
    broker = MagicMock()

    mock_ws_store = MagicMock()
    mock_ws_store.get_survivorship.return_value = {}

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store", return_value=mock_ws_store), \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["policy"].default_strategy == "most_complete"
    mock_ws_store.close.assert_called_once()


def test_review_sink_construction_failure_falls_back_to_none() -> None:
    """AdjudicationStore construction failing must not abort resolve_run."""
    store = _store_with_records([])
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore", side_effect=RuntimeError("db down")), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["review"] is None


def test_survivorship_lookup_failure_falls_back_to_default() -> None:
    """Workspace-store lookup failing must not abort resolve_run — safe default used."""
    store = _store_with_records([])
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store", side_effect=RuntimeError("db down")), \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["policy"].default_strategy == "most_complete"


# ── Chunked-resolver dispatch (large tabular sheets, e.g. 300K-row Data tabs) ─
# Regression coverage for a real incident: with no dispatch, ANY record count
# went through the in-memory resolve()'s O(block-size²) blocking/scoring pass
# unconditionally, and a 308,104-row sheet stalled ingestion for hours.

def _settings_stub(**overrides):
    base = dict(
        er_exact_id_match=True, er_chunk_threshold=100_000,
        er_min_key_selectivity=0.01, er_key_selectivity_sample_size=2000,
        rdb_dsn="postgresql://x",
    )
    base.update(overrides)
    return MagicMock(**base)


def test_below_threshold_uses_in_memory_resolve() -> None:
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(5)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=100)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


def test_above_threshold_uses_chunked_resolver() -> None:
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(10)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=5, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.PgChunkBackend") as mock_backend_cls, \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_chunked.return_value = iter([])
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_chunked.assert_called_once()
    mock_resolve.assert_not_called()
    mock_backend_cls.assert_called_once_with("postgresql://x", 1, ["name"])
    call_args = mock_chunked.call_args[0]
    assert call_args[0] == 1  # run_id
    assert call_args[2] == list(range(10))  # all_record_ids


def test_exact_ids_bypasses_chunking_regardless_of_size() -> None:
    """An id-keyed source resolves by exact equality — chunking has nothing
    to add there, so it must stay on the in-memory (exact_ids) path even
    when record count exceeds the chunk threshold."""
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(10)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=5, er_exact_id_match=True)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


# ── Key-selectivity guard ────────────────────────────────────────────────────
# Regression coverage for a real incident: a table whose match-key columns
# were each a single constant value across all 308,104 rows ran the FULL
# blocking/scoring pass (and separately, an unbatched per-cluster save)
# before reaching the exact same all-singleton outcome this guard reaches
# immediately, without ever running blocking at all.

def test_non_selective_key_skips_resolution_entirely() -> None:
    """All records share the exact same match text — zero identity signal.
    Resolution must be skipped and one entity materialized per record."""
    records = [ResolutionRecord(record_id=i, text="RP-00060001", payload={"n": i})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.05, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        store.save.return_value = 50
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["reporting_period_id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_not_called()
    mock_chunked.assert_not_called()
    saved_results = store.save.call_args[0][0]
    assert len(saved_results) == 50  # one entity per record, no merging attempted
    for _entity, members in saved_results:
        assert len(members) == 1  # every cluster is a genuine singleton


def test_selective_key_does_not_trigger_the_guard() -> None:
    """Distinct match text per record -> selectivity 1.0 -> normal resolve()
    path runs, guard must not interfere."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.01, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


def test_exact_ids_bypasses_the_selectivity_guard_too() -> None:
    """exact_ids mode never runs pairwise scoring in the first place —
    the selectivity guard must not even be evaluated for it."""
    records = [ResolutionRecord(record_id=i, text="CONST", payload={}) for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.01, er_exact_id_match=True)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()
    # resolve() must be called with exact_ids=True
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is True

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()
