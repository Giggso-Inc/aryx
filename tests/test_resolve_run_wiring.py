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
