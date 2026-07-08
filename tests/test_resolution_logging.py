"""Logging/correlation additions to the resolution funnel: run_id threading,
embedding-failure visibility, and block-count summary."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from aryx.models import ResolutionRecord
from aryx.resolution.run import _block_embeddings, resolve


def test_block_embeddings_failure_logs_warning_and_degrades(caplog) -> None:
    """A broker.embed() exception must be logged, not silently swallowed,
    while still falling back to string-only scoring for that batch."""
    records = [ResolutionRecord(record_id=i, text=f"rec {i}", payload={}) for i in range(3)]
    broker = MagicMock()
    broker.embed.side_effect = RuntimeError("embed service down")

    with caplog.at_level(logging.WARNING, logger="aryx.resolution.run"):
        result = _block_embeddings(records, broker, run_id=7)

    assert result == {}
    assert any("run_id=7" in r.getMessage() and "embed batch" in r.getMessage()
               for r in caplog.records)


def test_resolve_emits_run_id_correlated_summary(caplog) -> None:
    """resolve()'s block-count and final summary lines carry the given run_id."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={"name": "Acme Corp"}),
        ResolutionRecord(record_id=2, text="Zephyr Inc", payload={"name": "Zephyr Inc"}),
    ]
    broker = MagicMock()
    broker.embed.return_value = []

    with caplog.at_level(logging.INFO, logger="aryx.resolution.run"):
        results = resolve(records, broker, "Company", run_id=123)

    assert len(results) == 2  # dissimilar names, no merge
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("resolve run_id=123 blocks=") for m in messages)
    assert any(m.startswith("resolved run_id=123 records=2") for m in messages)
