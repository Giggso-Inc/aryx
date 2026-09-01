"""Deterministic co-occurrence linking for document-derived entities (Tier 0).

Entities extracted from free text carry no shared columns or keys the way
tabular rows do (see dimension_link.py), so neither the FK detector nor the
dimension-hub linker can find much to connect for a PDF-derived graph — a
real incident: a 97-type PDF batch ended with 63% of its entities isolated
even after every other linking tier ran successfully.

But documents carry a signal tabular data doesn't: entities extracted from
the SAME chunk of text (the same paragraph/sentence-group the extractor saw
in one call) are highly likely to be genuinely related — far more reliable
than the general-purpose LLM safety net's single-sample-per-type guess.
This module links every pair of entities that share a (doc_id, chunk_index)
— i.e. were mentioned in the same passage — via a deliberately weak,
distinctly-named edge (mentioned_with, confidence 0.5), the same convention
dimension_link.py uses for its category-level connections.

No LLM calls, no value-overlap scanning — purely structural, and a safe
no-op for tabular/XML data, which never carries chunk_index/doc_id
attributes at all.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from itertools import combinations

from aryx.config import get_settings
from aryx.models import Relationship
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _chunk_groups(entities: list[tuple[int, str, dict]]) -> dict[tuple[object, object], list[int]]:
    """Group entity ids by (doc_id, chunk_index).

    Both keys must be present — grouping by chunk_index alone would wrongly
    merge chunk 0 of one document with chunk 0 of an unrelated document
    sharing the same workspace.
    """
    groups: dict[tuple[object, object], list[int]] = defaultdict(list)
    for eid, _etype, attrs in entities:
        if not isinstance(attrs, dict):
            continue
        doc_id = attrs.get("doc_id")
        chunk_idx = attrs.get("chunk_index")
        if doc_id is None or chunk_idx is None:
            continue
        groups[(doc_id, chunk_idx)].append(eid)
    return groups


def detect_and_link_cooccurrence(estore: EntityStore) -> int:
    """Connect entities extracted from the same document chunk.

    Self-contained (queries current entities itself) and a safe no-op for
    workspaces with no document-derived entities. Intended to run once,
    after FK linking, before the LLM relate_isolated safety net — reducing
    how much that more expensive pass has left to do.
    """
    cfg = get_settings()
    if not cfg.cooccurrence_link_enabled:
        return 0

    entities = list(estore.list_entities())
    if not entities:
        return 0

    groups = _chunk_groups(entities)
    if not groups:
        logger.debug("cooccurrence_link: no document-derived (doc_id, chunk_index) entities — skipping")
        return 0

    max_pairs = cfg.cooccurrence_max_pairs_per_chunk
    rels: list[Relationship] = []
    chunks_linked = 0
    for (doc_id, chunk_idx), ids in groups.items():
        if len(ids) < 2:
            continue
        chunks_linked += 1
        pairs = list(combinations(ids, 2))
        if len(pairs) > max_pairs:
            logger.warning(
                "cooccurrence_link: doc=%s chunk=%s has %d entities (%d pairs) — "
                "exceeds cooccurrence_max_pairs_per_chunk=%d, capping",
                doc_id, chunk_idx, len(ids), len(pairs), max_pairs,
            )
            pairs = pairs[:max_pairs]
        for a, b in pairs:
            rels.append(Relationship(
                source_entity_id=a, target_entity_id=b,
                name="mentioned_with", confidence=0.5,
            ))

    if rels:
        estore.save_relationships(rels)
        logger.info(
            "cooccurrence_link: chunks_linked=%d edges=%d",
            chunks_linked, len(rels),
        )
    return len(rels)
