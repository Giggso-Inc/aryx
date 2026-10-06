"""Post-fold invariant for the raw-graph XML ingest.

After the structural-leaf and value-wrapper folds, no tag that still has the shape
of a plain scalar leaf (no attributes, no children, every occurrence) should be left
to land as its own entity type. When one is, its text sits in a separate entity
instead of on its parent (for a CPQ export: function scripts as ``ScriptText``
entities while the ``BmFunction`` rows carry no ``script_text``), and the engine
reads the parent only.

This module only detects and reports that state. It names no tag: the check is the
same shape test the fold uses, so it holds for any XML. The job is marked partial
(``note_hidden``) so a degraded ingest is visible in the job result and log, not
first noticed when Ask asks the wrong question.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawNode
from aryx.cpq_ingestion.raw_graph.structural_leaf import is_structural_leaf_tag
from aryx.raven_log import raven_log
from aryx.worker.job_partial import note_hidden

logger = logging.getLogger(__name__)

REASON_FOLD_DISABLED = "STRUCTURAL_LEAF_FOLD_DISABLED"
REASON_KEPT_AFTER_FOLD = "LEAF_TAG_KEPT_AFTER_FOLD"


def find_unfolded_leaf_tags(
    by_tag: dict[str, list[RawNode]], edges: Iterable[RawEdge],
) -> dict[str, int]:
    """{tag: node count} for every tag in `by_tag` that is still a structural leaf."""
    parent_ids = {edge.source_id for edge in edges}
    return {
        tag: len(nodes) for tag, nodes in by_tag.items()
        if nodes and is_structural_leaf_tag(nodes, parent_ids)
    }


def audit_unfolded_leaf_tags(
    by_tag: dict[str, list[RawNode]], edges: Iterable[RawEdge], *,
    fold_enabled: bool, log_id: str | None = None, source_key: str = "",
) -> dict[str, int]:
    """Detect, log and count unfolded leaf tags; returns them ({} when none).

    A diagnostic: an unexpected error here is logged and swallowed so it can never abort the ingest."""
    try:
        unfolded = find_unfolded_leaf_tags(by_tag, edges)
    except Exception:  # noqa: BLE001
        logger.warning("raw_graph leaf audit did=%s source_key=%s failed; skipped", log_id, source_key, exc_info=True)
        return {}
    if not unfolded:
        return {}
    reason = REASON_KEPT_AFTER_FOLD if fold_enabled else REASON_FOLD_DISABLED
    shown = dict(sorted(unfolded.items(), key=lambda kv: -kv[1])[:20])
    logger.warning(
        "raw_graph leaf audit did=%s source_key=%s: %d leaf tag(s) will land as their own entities "
        "instead of on their parent (%s): %s",
        log_id, source_key, len(unfolded), reason, shown,
    )
    raven_log(
        "WARN", "P3", "ingest.raw_graph.leaf_unfolded leaf tags will land as separate entities",
        error_code="ARYX_ING_LEAF_UNFOLDED",
        context={
            "log_id": log_id, "source_key": source_key, "tags_unfolded": len(unfolded),
            "tags": shown, "reason_code": reason,
            "selected_option": "land_as_entities", "available_options": ["fold", "land_as_entities"],
            "decision": "degraded", "result": "degraded", "fold_enabled": fold_enabled,
        },
    )
    note_hidden(log_id)
    return unfolded
