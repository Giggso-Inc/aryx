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


def test_block_embeddings_dedupes_identical_text_before_calling_broker() -> None:
    """§2 (2026-10-04): two records sharing an identical text value must
    produce exactly one broker.embed() call for that batch, with only the
    distinct texts -- not one call per record. PR review N1 flagged this
    fix as shipped with no test coverage; this pins the actual dedup
    behavior, not just that embedding happens at all."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={}),
        ResolutionRecord(record_id=2, text="Acme Corp", payload={}),  # exact duplicate
        ResolutionRecord(record_id=3, text="Globex Inc", payload={}),
    ]
    broker = MagicMock()
    broker.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]  # one vector per UNIQUE text

    result = _block_embeddings(records, broker, run_id=1)

    broker.embed.assert_called_once()
    (called_texts,), _ = broker.embed.call_args
    assert sorted(called_texts) == ["Acme Corp", "Globex Inc"]
    assert len(called_texts) == 2  # not 3 -- the duplicate was not re-embedded


def test_block_embeddings_gives_every_duplicate_record_its_texts_vector() -> None:
    """Zero change to resolution correctness: every original record_id still
    gets the vector for its own text, including both records that shared a
    deduped text value."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={}),
        ResolutionRecord(record_id=2, text="Acme Corp", payload={}),
        ResolutionRecord(record_id=3, text="Globex Inc", payload={}),
    ]
    broker = MagicMock()

    def fake_embed(texts):
        return [[float(len(t))] for t in texts]

    broker.embed.side_effect = fake_embed

    result = _block_embeddings(records, broker, run_id=1)

    assert result[1] == result[2]  # same text -> same vector
    assert result[1] != result[3]  # different text -> different vector
    assert set(result.keys()) == {1, 2, 3}  # every record_id got a vector


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
