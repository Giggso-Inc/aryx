"""Exact-id resolution path and pair-score bucketing for the funnel.

Split out of `resolution/run.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03) — the two functions here call neither `get_settings` nor
`adjudicate` and are never themselves patched (confirmed via grep), unlike
the rest of the module. See `resolution/run.py`'s docstring for why the
remaining functions stay together.
"""
from __future__ import annotations

import logging

from aryx.models import ResolutionRecord
from aryx.raven_log import raven_log
from aryx.resolution.blocking import normalize
from aryx.resolution.cluster import UnionFind

logger = logging.getLogger(__name__)


def _partition_pair_scores(
    union: UnionFind, pair_scores: dict[tuple[int, int], float],
) -> dict[int, dict[tuple[int, int], float]]:
    """Bucket pair_scores by cluster root ONCE, before materializing clusters.

    cluster_edges() (confidence.py) scans its whole pair_scores argument for
    every call. Passing the SAME full, run-wide pair_scores dict to every
    cluster's _materialize() call makes total cost O(clusters x edges)
    instead of O(edges) — a real incident: for a run with ~106,000 clusters
    and 14.3 million pair scores, that is over a trillion dict-item checks.
    Bucketing once (union.find() is O(1) amortized with path compression,
    already applied by earlier union() calls) and handing each cluster only
    its OWN small subset restores the correct O(edges + clusters) cost.
    """
    by_root: dict[int, dict[tuple[int, int], float]] = {}
    for (left, right), score in pair_scores.items():
        root = union.find(left)
        by_root.setdefault(root, {})[(left, right)] = score
    return by_root


def _resolve_exact(
    records: list[ResolutionRecord],
    union: UnionFind,
    pair_scores: dict[tuple[int, int], float],
    run_id: int | None,
) -> int:
    """Exact-equality grouping for id-keyed data — no fuzzy scoring.

    Fuzzy similarity is semantically invalid for opaque identifiers:
    sequential ids like 18722401146 vs 18722401147 score 0.909+ on string
    similarity and transitively collapse whole id ranges into one entity.
    Here two records merge ONLY when their normalized match text is
    identical. O(n), no embedding or LLM calls, no review-queue writes.

    Records with empty/blank match text NEVER merge — each stays its own
    entity. (The fuzzy path scores '' vs '' as 1.0, silently merging every
    record that lacks the match-key attribute.)

    Returns:
        Number of merge operations performed.
    """
    groups: dict[str, list[int]] = {}
    empty_text = 0
    for record in records:
        key = normalize(record.text)
        if not key:
            empty_text += 1
            continue
        groups.setdefault(key, []).append(record.record_id)

    merged = 0
    for member_ids in groups.values():
        if len(member_ids) <= 1:
            continue
        # Chain pairs (k-1 edges at 1.0), not all O(k^2) pairs: sufficient for
        # cluster_edges' contract (any within-cluster edge >= threshold) while
        # bounding memory on pathological duplicate sets.
        anchor = member_ids[0]
        for other in member_ids[1:]:
            union.union(anchor, other)
            pair_scores[(anchor, other)] = 1.0
            merged += 1
    logger.info("resolve run_id=%s mode=exact_ids groups=%d records=%d merged=%d empty_text=%d",
                run_id, len(groups), len(records), merged, empty_text)
    exact_ctx = {"pipeline_run_id": run_id, "mode": "exact_ids", "groups": len(groups),
                 "records": len(records), "merged": merged, "empty_text": empty_text}
    if empty_text:
        # Blank match text never merges: each such record stays its own entity.
        raven_log("WARN", "P3", "ingest.resolve.empty_match_text records without match text kept separate",
                  error_code="ARYX_ING_RESOLVE_EMPTY_MATCH_TEXT",
                  context={"selected_option": "keep_separate", "available_options": ["merge", "keep_separate"],
                           "reason_code": "EMPTY_MATCH_TEXT", "policy_version": "resolve_exact_v1",
                           **exact_ctx})
    else:
        raven_log("DEBUG", "P4", "ingest.resolve.exact_grouped exact-id grouping done",
                  context={"selected_option": "group_exact", "available_options": ["group_exact"],
                           "reason_code": "EXACT_IDS", "policy_version": "resolve_exact_v1",
                           **exact_ctx})
    return merged
