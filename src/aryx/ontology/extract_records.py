"""Verbatim-span gate + mention-to-RawRecord mapping for entity extraction.

Split out of `ontology/extract.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

from aryx.models import DocumentChunk, RawRecord, SourceRef


def _verbatim_ok(name: str, span: str) -> bool:
    return name.lower() in span.lower()


def _mentions_to_records(chunk: DocumentChunk, result: dict) -> tuple[list[RawRecord], int]:
    """Apply the verbatim-span gate; returns (accepted_records, rejected_count)."""
    records: list[RawRecord] = []
    rejected = 0
    for i, mention in enumerate(result.get("mentions", [])):
        name = mention.get("name", "")
        span = mention.get("span", "") or name
        if not name or not mention.get("type") or not _verbatim_ok(name, span):
            rejected += 1
            continue
        mention_id = f"{chunk.doc_id}:{chunk.chunk_index}:{i}"
        records.append(RawRecord(
            source=SourceRef(
                system=chunk.source.system,
                dataset=chunk.source.dataset,
                record_id=mention_id,
            ),
            payload={
                "type": mention["type"],
                "name": name,
                "doc_id": chunk.doc_id,
                "chunk_index": chunk.chunk_index,
                "span": span,
                **(mention.get("attributes") or {}),
            },
        ))
    return records, rejected
