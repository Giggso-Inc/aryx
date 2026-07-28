"""Tests for extract_mentions() chunk-level concurrency and progress callback.

Bug: extraction processed one chunk at a time — a 50-page PDF (~330 chunks)
measured at 36 minutes wall-clock, so a 1000+ page document would take many
hours serially and could exceed per_doc_timeout (default 2h) before it
finished, silently discarding every mention extracted so far (the full
record list was only returned at the very end of the call).

Fix: chunks now run through a bounded ThreadPoolExecutor
(ARYX_EXTRACT_MENTION_WORKERS), and an optional on_progress callback fires
every ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS completed chunks so a
caller can persist partial progress instead of only getting a result at
the very end.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from aryx.models import DocumentChunk, SourceRef
from aryx.ontology.extract import extract_mentions


def _chunk(idx: int, text: str = "Some arbitrary document text.") -> DocumentChunk:
    return DocumentChunk(
        doc_id="deadbeef" * 8, chunk_index=idx, text=text,
        source=SourceRef(system="document", dataset="upload", record_id=f"doc:{idx}"),
    )


def _mentions_result(names: list[str]) -> dict:
    return {"mentions": [
        {"name": n, "type": "Entity", "span": n} for n in names
    ]}


def test_chunks_run_concurrently_not_strictly_one_at_a_time(monkeypatch):
    """With workers > 1, multiple chunks' LLM calls must overlap in time —
    proves throughput isn't still gated to one in-flight call, which is
    what made large documents scale linearly (and badly) with page count."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_WORKERS", "4")
    from aryx.config import get_settings
    get_settings.cache_clear()

    lock = threading.Lock()
    in_flight = {"current": 0, "peak": 0}

    def slow(*args, **kwargs):
        with lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        time.sleep(0.05)
        with lock:
            in_flight["current"] -= 1
        return _mentions_result(["Acme Corp"])

    chunks = [_chunk(i) for i in range(8)]
    with patch("aryx.ontology.extract.complete_json", side_effect=slow):
        records = extract_mentions(chunks, broker=MagicMock())

    assert len(records) == 8
    assert in_flight["peak"] > 1, (
        "expected multiple chunk extractions in flight at once; "
        f"observed peak concurrency={in_flight['peak']}"
    )
    get_settings.cache_clear()


def test_single_worker_config_preserves_fully_sequential_behavior(monkeypatch):
    """ARYX_EXTRACT_MENTION_WORKERS=1 must behave like the old strictly-
    sequential code — no concurrent calls in flight, for setups (e.g. a
    single local Ollama instance) where parallel requests only add queue
    overhead with no real throughput gain."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_WORKERS", "1")
    from aryx.config import get_settings
    get_settings.cache_clear()

    lock = threading.Lock()
    in_flight = {"current": 0, "peak": 0}

    def slow(*args, **kwargs):
        with lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        time.sleep(0.01)
        with lock:
            in_flight["current"] -= 1
        return _mentions_result(["Acme Corp"])

    chunks = [_chunk(i) for i in range(5)]
    with patch("aryx.ontology.extract.complete_json", side_effect=slow):
        records = extract_mentions(chunks, broker=MagicMock())

    assert len(records) == 5
    assert in_flight["peak"] == 1
    get_settings.cache_clear()


def test_on_progress_fires_at_configured_cadence_and_at_the_end(monkeypatch):
    """on_progress must fire every N completed chunks (durability flush
    cadence) and always once more at the very end, even when the total
    isn't a multiple of N — otherwise the last partial batch of mentions
    would never be persisted."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_WORKERS", "2")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS", "3")
    from aryx.config import get_settings
    get_settings.cache_clear()

    calls: list[tuple[int, int]] = []
    lock = threading.Lock()

    def on_progress(completed, total, new_records):
        with lock:
            calls.append((completed, total))

    chunks = [_chunk(i) for i in range(7)]  # not a multiple of flush=3
    with patch("aryx.ontology.extract.complete_json",
               return_value=_mentions_result(["Acme Corp"])):
        records = extract_mentions(chunks, broker=MagicMock(), on_progress=on_progress)

    assert len(records) == 7
    completed_values = sorted(c for c, _ in calls)
    assert completed_values[-1] == 7, "must flush once more at the very end"
    assert all(total == 7 for _, total in calls)
    assert len(calls) >= 3, "expected flushes at 3, 6, and the final 7"
    get_settings.cache_clear()


def test_on_progress_receives_only_new_records_since_last_flush(monkeypatch):
    """Each flush's new_records must be the batch extracted since the
    previous flush, not the cumulative total — otherwise a caller
    persisting on every call would double-count mentions."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_WORKERS", "1")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS", "2")
    from aryx.config import get_settings
    get_settings.cache_clear()

    batches: list[int] = []

    def on_progress(completed, total, new_records):
        batches.append(len(new_records))

    chunks = [_chunk(i) for i in range(4)]
    with patch("aryx.ontology.extract.complete_json",
               return_value=_mentions_result(["Acme Corp"])):
        records = extract_mentions(chunks, broker=MagicMock(), on_progress=on_progress)

    assert len(records) == 4
    assert sum(batches) == 4, "sum of per-flush batches must equal total mentions"
    assert all(b <= 2 for b in batches), "each flush should only carry its own new batch"
    get_settings.cache_clear()


def test_one_chunk_erroring_never_blocks_sibling_chunks_running_concurrently(monkeypatch):
    """Raven review (PR #120): the docstring claims one chunk's exhausted
    retries never block the others, but that was only exercised serially
    (test_extract_mentions_retry.py's workers=1 default). This proves it
    holds when the failing chunk runs CONCURRENTLY alongside succeeding
    ones — a chunk stuck in retry/backoff must not stall or drop results
    from chunks finishing in parallel on other worker threads."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_WORKERS", "4")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "2")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0.01")
    from aryx.config import get_settings
    get_settings.cache_clear()

    def per_chunk(broker, tier, system, user, schema):
        import json as _json
        payload = _json.loads(user)
        if payload["chunk_index"] == 2:
            raise RuntimeError("provider error — this chunk always fails")
        return _mentions_result([f"Entity{payload['chunk_index']}"])

    chunks = [_chunk(i) for i in range(6)]
    with patch("aryx.ontology.extract.complete_json", side_effect=per_chunk):
        records = extract_mentions(chunks, broker=MagicMock())

    names = {r.payload["name"] for r in records}
    assert names == {"Entity0", "Entity1", "Entity3", "Entity4", "Entity5"}, (
        "every chunk except the permanently-failing one must still contribute"
    )
    get_settings.cache_clear()


def test_no_on_progress_callback_is_optional(monkeypatch):
    """extract_mentions() must work fine with on_progress omitted entirely —
    existing callers that don't pass it must be unaffected."""
    from aryx.config import get_settings
    get_settings.cache_clear()

    with patch("aryx.ontology.extract.complete_json",
               return_value=_mentions_result(["Acme Corp"])):
        records = extract_mentions([_chunk(0), _chunk(1)], broker=MagicMock())

    assert len(records) == 2
    get_settings.cache_clear()
