"""Regression tests for extract_mentions()'s LLM-extraction retry.

Bug: "Review discovered types" showed 0 entity types intermittently on the
same/similar PDF across different upload instances. Root cause (confirmed
by reading the code): extract_mentions() called complete_json() once per
chunk with no retry — any exception (malformed JSON from the model, a
transient provider hiccup) silently dropped that chunk. If it hit every
chunk in one run, the whole document produced zero discovered types,
indistinguishable in the UI from "this document has no entities."

Fix: bounded retry (ARYX_EXTRACT_MENTION_RETRIES, default 3) with linear
backoff around each chunk's complete_json() call.

These tests use synthetic chunks with arbitrary, made-up text — the retry
logic operates purely at the LLM-response layer and is completely
content-agnostic, so it works identically for any real PDF's extracted
text; no PDF fixture is needed to exercise it.
"""
from __future__ import annotations

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


def test_transient_failure_then_success_recovers_the_chunk(monkeypatch):
    """A chunk whose first call fails but second succeeds must still
    contribute its mentions — no permanent data loss from one hiccup."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "3")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()

    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("malformed JSON from model")
        return _mentions_result(["Acme Corp"])

    with patch("aryx.ontology.extract.complete_json", side_effect=flaky):
        records = extract_mentions([_chunk(0)], broker=MagicMock())

    assert calls["n"] == 2, "must retry after the first transient failure"
    assert len(records) == 1
    assert records[0].payload["name"] == "Acme Corp"
    get_settings.cache_clear()


def test_persistent_failure_on_one_chunk_does_not_block_other_chunks(monkeypatch):
    """A chunk that fails every attempt is skipped, but sibling chunks in
    the same document must still be processed normally."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "2")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()

    def per_chunk(broker, tier, system, user, schema):
        import json as _json
        payload = _json.loads(user)
        if payload["chunk_index"] == 0:
            raise RuntimeError("provider error")
        return _mentions_result(["Globex"])

    with patch("aryx.ontology.extract.complete_json", side_effect=per_chunk):
        records = extract_mentions([_chunk(0), _chunk(1)], broker=MagicMock())

    assert len(records) == 1
    assert records[0].payload["name"] == "Globex"
    get_settings.cache_clear()


def test_all_chunks_failing_returns_empty_list_without_raising(monkeypatch, caplog):
    """The document-level "zero discovered types" outcome must be a clean
    empty list, not an unhandled exception — and the log must clarify it
    was an extraction failure, not an empty document."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "2")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()

    with patch("aryx.ontology.extract.complete_json",
               side_effect=RuntimeError("model unavailable")):
        with caplog.at_level("WARNING"):
            records = extract_mentions([_chunk(0), _chunk(1)], broker=MagicMock())

    assert records == []
    assert any("due to LLM extraction failure, not an empty document" in r.message
               for r in caplog.records)
    get_settings.cache_clear()


def test_no_retry_overhead_when_first_attempt_succeeds(monkeypatch):
    """The common case (LLM call succeeds first try) must not pay any
    retry/backoff cost — complete_json is called exactly once per chunk."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "3")
    from aryx.config import get_settings
    get_settings.cache_clear()

    mock_complete = MagicMock(return_value=_mentions_result(["Initech"]))
    with patch("aryx.ontology.extract.complete_json", mock_complete):
        records = extract_mentions([_chunk(0)], broker=MagicMock())

    assert mock_complete.call_count == 1
    assert len(records) == 1
    get_settings.cache_clear()


def test_retry_attempt_count_is_configurable(monkeypatch):
    """ARYX_EXTRACT_MENTION_RETRIES controls exactly how many attempts are
    made — proves the retry budget is dynamic config, not a hardcoded
    number baked into the function."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "5")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()

    mock_complete = MagicMock(side_effect=RuntimeError("always fails"))
    with patch("aryx.ontology.extract.complete_json", mock_complete):
        records = extract_mentions([_chunk(0)], broker=MagicMock())

    assert mock_complete.call_count == 5
    assert records == []
    get_settings.cache_clear()


def test_works_identically_for_arbitrary_never_before_seen_text(monkeypatch):
    """Proves the retry mechanism is content-agnostic: an arbitrary chunk
    of text invented purely for this test, run through a flaky-then-healthy
    LLM call, recovers exactly the same way real PDF text would — nothing
    about the retry logic depends on document content."""
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRIES", "3")
    monkeypatch.setenv("ARYX_EXTRACT_MENTION_RETRY_DELAY", "0")
    from aryx.config import get_settings
    get_settings.cache_clear()

    novel_text = "Zylophant Dynamics announced a partnership with Quorvex Labs in Q9."
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("truncated JSON")
        return _mentions_result(["Zylophant Dynamics", "Quorvex Labs"])

    with patch("aryx.ontology.extract.complete_json", side_effect=flaky):
        records = extract_mentions([_chunk(0, text=novel_text)], broker=MagicMock())

    names = {r.payload["name"] for r in records}
    assert names == {"Zylophant Dynamics", "Quorvex Labs"}
    get_settings.cache_clear()
