"""Pure value helpers shared by AryxAskThreadStore's read/write paths.

Split out of `store/ask_thread_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

import json
import re
from typing import Any


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_json(value: Any) -> Any:
    """Parse a JSON column value that may arrive as a string or already-parsed.

    Postgres JSONB columns come back as dict/list (psycopg auto-decodes).
    Shay's gg_* tables store the same data as CLOB on Oracle (no native JSON
    type there), so oracledb returns plain text -- this normalizes both to
    the same Python shape the caller expects.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def normalize_grounding_citations(grounding: Any) -> list[dict[str, Any]]:
    """Return frontend citation objects from the grounding contract."""
    if not isinstance(grounding, dict):
        return []
    raw_citations = grounding.get("citations")
    if not isinstance(raw_citations, list):
        return []

    citations = []
    for index, citation in enumerate(raw_citations):
        if not isinstance(citation, dict):
            continue
        label = citation.get("label") or citation.get("entity_name")
        if not isinstance(label, str) or not label.strip():
            continue
        citations.append({
            "entity_id": _as_int(
                citation.get("entity_id"),
                _as_int(citation.get("marker"), index),
            ),
            "label": label,
            "type": citation.get("type") or citation.get("entity_type"),
        })
    return citations


def normalize_thread_title(question: str, max_len: int = 80) -> str:
    """Return the deterministic first-prompt title for an Ask thread."""
    title = re.sub(r"\s+", " ", question.strip())
    if not title:
        return "New chat"
    if len(title) <= max_len:
        return title
    return title[: max_len - 1].rstrip() + "..."
