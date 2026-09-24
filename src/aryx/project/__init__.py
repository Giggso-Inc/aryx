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

from aryx.project.project_full import ProjectProgress, _entity_iri, project_graph
from aryx.project.project_incremental import project_incremental
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
    on_progress: ProjectProgress | None = None,
    pct_range: tuple[int, int] = (90, 95),
    **kwargs,
) -> dict[str, int]:
    """Pick incremental vs full rebuild (G8 mode=auto).

    Incremental when a watermark exists AND the dirty set is under
    ``dirty_ratio_max`` (env ARYX_PROJECT_DIRTY_MAX overrides) of all
    entities; full rebuild otherwise — it remains the correctness anchor.

    on_progress/pct_range only reach project_graph()'s per-row scaled
    reporting (docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md §6.4) —
    project_incremental() has no equivalent internal granularity, so an
    incremental run instead reports once at pct_range's start and once at
    its end. This is the same entry/exit-only shape project_graph() itself
    used to have before that fix, but the risk it addressed (a long-running
    stage looking hung to an external timeout watchdog) does not apply
    here: an incremental run only touches the entities/relationships dirty
    since the last watermark, by design a small slice of the graph, so it
    is expected to complete quickly.
    """
    try:
        dirty_ratio_max = float(os.environ.get("ARYX_PROJECT_DIRTY_MAX",
                                               dirty_ratio_max))
    except ValueError:
        pass
    lo, hi = pct_range
    since = pstore.watermark()
    if since is not None:
        total = pstore.total_entities()
        dirty = len(pstore.dirty_entities(since))
        if total and dirty / total < dirty_ratio_max:
            if on_progress is not None:
                on_progress("Project", lo, "incremental projection starting")
            counts = project_incremental(store, pstore, graph, **kwargs)
            if on_progress is not None:
                on_progress("Project", hi,
                            f"{counts.get('entities', 0)} entities updated (incremental)")
            return counts
    counts = project_graph(store, graph, on_progress=on_progress,
                           pct_range=pct_range, **kwargs)
    pstore.mark_projected([e[0] for e in store.list_entities()])
    pstore.advance_watermark()
    return counts
