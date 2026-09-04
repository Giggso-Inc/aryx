"""Text-normalization and phrase/token matching for the brief-driven overview.

Split out of `explore.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from aryx.display_name import display_name

_STOPWORDS = {
    "a", "an", "and", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with",
}
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _normalise_text(text: str) -> str:
    """Lowercase + split camel case so brief text can match ontology labels."""
    split = _CAMEL_RE.sub(" ", str(text or ""))
    return " ".join(part.lower() for part in _WORD_RE.findall(split))


def _tokens(text: str) -> set[str]:
    """Tokenise a label, dropping tiny/common words that drown the match signal."""
    return {
        tok for tok in _normalise_text(text).split()
        if (len(tok) > 1 or tok.isdigit()) and tok not in _STOPWORDS
    }


def _matches(query_text: str, candidate: str) -> bool:
    """Return True when text overlaps by phrase or meaningful token."""
    q_norm = _normalise_text(query_text)
    c_norm = _normalise_text(candidate)
    if not q_norm or not c_norm:
        return False
    if _tokens(query_text) & _tokens(candidate):
        return True
    return len(q_norm) >= 4 and len(c_norm) >= 4 and (q_norm in c_norm or c_norm in q_norm)


def _entity_match_text(entity_id: int, entity_type: str, attrs: dict[str, Any]) -> str:
    """Build a compact text block used to decide if an entity matches the brief."""
    parts = [entity_type, display_name(attrs or {}, entity_id)]
    for value in (attrs or {}).values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)


def _domain_matches(
    entities: list[tuple[int, str, dict[str, Any]]], query_text: str,
) -> tuple[set[int], set[str]]:
    """Match the query against entity types first, then against entity text."""
    if not _tokens(query_text):
        return set(), set()

    ids_by_type: dict[str, set[int]] = defaultdict(set)
    for entity_id, entity_type, _attrs in entities:
        ids_by_type[entity_type].add(entity_id)

    matched_types = {
        entity_type for entity_type in ids_by_type
        if _matches(query_text, entity_type)
    }
    matched_ids = {
        entity_id for entity_type in matched_types
        for entity_id in ids_by_type[entity_type]
    }

    for entity_id, entity_type, attrs in entities:
        if _matches(query_text, _entity_match_text(entity_id, entity_type, attrs or {})):
            matched_ids.add(entity_id)
            matched_types.add(entity_type)

    return matched_ids, matched_types
