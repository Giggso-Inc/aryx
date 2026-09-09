"""Knowledge-graph projection orchestration (stage 5d): RDB -> FalkorDB.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`project_full.py` (full rebuild — `project_graph`/`_entity_iri`) and
`project_incremental.py` (dirty-set update — `project_incremental`), both
re-imported here. `project_auto` — the mode-picking entry point — stays
here as the orchestrator. Zero whitebox test patches exist anywhere
against `aryx.project.*` (confirmed via grep), so the split was purely
mechanical.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.graph import FalkorStore

from aryx.project_full import ProjectProgress, _entity_iri, project_graph
from aryx.project_incremental import project_incremental
from aryx.store.entity_store import EntityStore

__all__ = [
    "ProjectProgress",
    "project_auto",
    "project_graph",
    "project_incremental",
]


def project_auto(
    store: "EntityStore",
    pstore,
    graph: "FalkorStore",
    dirty_ratio_max: float = 0.30,
    **kwargs,
) -> dict[str, int]:
    """Pick incremental vs full rebuild (G8 mode=auto).

    Incremental when a watermark exists AND the dirty set is under
    ``dirty_ratio_max`` (env ARYX_PROJECT_DIRTY_MAX overrides) of all
    entities; full rebuild otherwise — it remains the correctness anchor.
    """
    try:
        dirty_ratio_max = float(os.environ.get("ARYX_PROJECT_DIRTY_MAX",
                                               dirty_ratio_max))
    except ValueError:
        pass
    since = pstore.watermark()
    if since is not None:
        total = pstore.total_entities()
        dirty = len(pstore.dirty_entities(since))
        if total and dirty / total < dirty_ratio_max:
            return project_incremental(store, pstore, graph, **kwargs)
    counts = project_graph(store, graph, **kwargs)
    pstore.mark_projected([e[0] for e in store.list_entities()])
    pstore.advance_watermark()
    return counts
