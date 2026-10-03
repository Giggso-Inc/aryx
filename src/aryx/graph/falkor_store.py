"""FalkorDB writer for the knowledge-graph projection (stage 5d).

The graph is a rebuildable projection of the RDB (the source of truth), so the
writer always wipes and rebuilds. Entity nodes carry their ontology type;
provenance edges link entities to source records; REL edges connect entities.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the pure
sanitization helpers (`_sanitize_ident`/`_lift_props`/`_safe_labels`/
`_display_name`) live in `graph.falkor_sanitize` (re-imported here for
`test_protege_parity.py`/`test_doc_discovery.py`'s direct imports), and
`FalkorStore`'s write methods live in two mixins — `graph.falkor_write_
entities` and `graph.falkor_write_relationships` — since no test patches an
individual method (only the whole `FalkorStore` class, or `FalkorDB` in
`__init__`), moving them carries no patch-retargeting risk. `FalkorStore`
itself stays importable at this exact path (`aryx.graph.falkor_store:
FalkorStore`), which `ports/config.py`'s adapter lookup depends on.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from aryx.graph.falkor_sanitize import (
    _LABEL_RE,
    _display_name,
    _lift_props,
    _safe_labels,
    _sanitize_ident,
)
from aryx.graph.falkor_write_entities import _FalkorEntityWriteMixin
from aryx.graph.falkor_write_relationships import _FalkorRelationshipMixin
from aryx.raven_log import current_run_id, raven_log, would_log

__all__ = [
    "FalkorStore",
    "_display_name",
    "_lift_props",
    "_safe_labels",
    "_sanitize_ident",
]

logger = logging.getLogger(__name__)


def _index_failed(index: str, exc: Exception, impact: str) -> None:
    """Record a failed, non-fatal index creation; writes degrade to a full scan."""
    raven_log("WARN", "P3", f"ingest.graph.index_failed index on {index} not created",
              error_code="ARYX_ING_GRAPH_INDEX_FAILED",
              context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                       "backoff_ms": 0, "recovery_selected": "continue_without_index",
                       "fallback_target": impact, "exit_condition": "degraded", "result": "degraded",
                       "index": index, "backend": "falkordb", "trace_id": current_run_id()})


class FalkorStore(_FalkorEntityWriteMixin, _FalkorRelationshipMixin):
    """Writes entity / provenance / relationship graph elements to FalkorDB."""

    def __init__(self, url: str, graph: str = "aryx") -> None:
        """Connect from a redis:// URL and select a named graph.

        Args:
            url: FalkorDB connection URL, e.g. redis://falkordb:6379.
            graph: Graph key to write into.
        """
        parsed = urlparse(url)
        self._db = FalkorDB(host=parsed.hostname or "localhost",
                            port=parsed.port or 6379,
                            username=parsed.username or None,
                            password=parsed.password or None)
        self._graph = self._db.select_graph(graph)
        # Index-worthy property names observed while writing entities; flushed
        # to CREATE INDEX statements by ensure_indexes().
        self._index_candidates: set[str] = set()

    def run_read_only(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """Execute an arbitrary query via FalkorDB's server-enforced read-only
        mode (GRAPH.RO_QUERY) -- rejects any write operation at the database
        level, not just an application-side keyword blacklist.

        Used by graph_api.py's /graph/cypher endpoint (found by post-merge
        review: that endpoint previously called store.run(), a method that
        never existed on this class -- every call crashed with
        AttributeError -- and relied solely on a regex keyword blacklist
        that doesn't catch e.g. a write-capable CALL procedure).
        """
        return self._graph.ro_query(query, params=params or {}).result_set

    def clear(self) -> None:
        """Delete the whole graph for a clean rebuild.

        Re-creates the index on Entity.id immediately after — delete() wipes
        it along with everything else, and every add_entity() MERGE matches
        on {id: $id}. Without the index, that MERGE does a full label scan
        per call, so the entity-write loop degrades from O(1) to O(n) per
        write (O(n^2) overall) as the graph grows — this is a pure write-
        performance fix, not a behavior/correctness change.
        """
        try:
            self._graph.delete()
        except Exception as exc:  # graph may not exist yet  # noqa: BLE001
            raven_log("DEBUG", "P4", "ingest.graph.clear_skipped graph did not exist yet",
                      context={"selected_option": "continue", "available_options": ["continue", "abort"],
                               "reason_code": "GRAPH_NOT_PRESENT", "policy_version": "falkor_clear_v1",
                               "error_class": type(exc).__name__, "backend": "falkordb"})
        try:
            self._graph.query("CREATE INDEX FOR (e:Entity) ON (e.id)")
        except Exception as exc:  # noqa: BLE001 — perf optimization only; MERGE still works without it
            logger.warning("falkor: failed to create index on Entity.id, "
                           "writes will fall back to full-scan MERGE: %s", exc)
            _index_failed("Entity.id", exc, "full_scan_merge")
        try:
            # Same fix as Entity.id above, for the SAME reason — add_provenance's
            # MERGE (s:Source {system, dataset, record_id}) had no index, so
            # every call label-scanned every Source node written so far this
            # run: O(1) per write growing to O(n), O(n^2) overall. Confirmed
            # live (docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md): this
            # was the dominant cost of the "slow after 90%" symptom — ~69 of
            # ~70 minutes in the Project stage on an 83k-entity workspace,
            # and severe enough that an external timeout watchdog marked a
            # genuinely-still-working ingestion job "failed" mid-run.
            self._graph.query("CREATE INDEX FOR (s:Source) ON (s.record_id)")
        except Exception as exc:  # noqa: BLE001 — perf optimization only
            logger.warning("falkor: failed to create index on Source.record_id, "
                           "provenance writes will fall back to full-scan MERGE: %s", exc)
            _index_failed("Source.record_id", exc, "full_scan_merge")
        try:
            # /graph's reader issues one query per relationship name, filtering
            # on r.name (see reader.py's subgraph()) — with no index on the
            # generic REL edge type, each of those queries full-scans every
            # relationship in the graph. Confirmed live: on a ~600K-node,
            # ~1.2M-relationship workspace, a single such query took ~1095ms;
            # /graph's ~20 relationship-name queries stacked in one request
            # exceeded FalkorDB's TIMEOUT, aborting with "Query timed out" and
            # a 500 from the API. This index took the same query to ~3ms.
            self._graph.query("CREATE INDEX FOR ()-[r:REL]-() ON (r.name)")
        except Exception as exc:  # noqa: BLE001 — perf optimization only
            logger.warning("falkor: failed to create index on REL.name, "
                           "relationship-name lookups will fall back to full-scan: %s", exc)
            _index_failed("REL.name", exc, "full_scan_lookup")

    def ensure_indexes(self) -> int:
        """Create exact-match indexes for Entity lookups (idempotent).

        Indexes ``type``, ``name`` and every key-like lifted property observed
        during entity writes (``*_id``, ``guid``, ``variable_name``, ...).
        FalkorDB errors on duplicate index creation, so each statement is
        attempted independently and failures are treated as already-exists.
        ``id`` is indexed by clear(). Returns the number of CREATE INDEX
        statements that succeeded.
        """
        created = 0
        for prop in sorted({"type", "name", "isolated"} | self._index_candidates):
            if not _LABEL_RE.match(prop):
                continue
            try:
                self._graph.query(f"CREATE INDEX FOR (e:Entity) ON (e.{prop})")
                created += 1
            except Exception as exc:  # noqa: BLE001 — duplicate index or unsupported
                logger.debug("falkor: index on Entity.%s not created: %s", prop, exc)
                if would_log("DEBUG"):
                    raven_log("DEBUG", "P4", "ingest.graph.index_not_created index already exists or unsupported",
                              context={"selected_option": "skip", "available_options": ["create", "skip"],
                                       "reason_code": "CREATE_FAILED", "policy_version": "falkor_indexes_v1",
                                       "property": prop, "error_class": type(exc).__name__})
        logger.info("falkor: ensure_indexes created=%d candidates=%d",
                    created, len(self._index_candidates))
        raven_log("DEBUG", "P4", "ingest.graph.indexes_ensured",
                  context={"task_id": current_run_id(), "final_status": "complete", "duration_ms": 0,
                           "stage": "graph_indexes", "result": "ok", "reason_code": "INDEXES_ENSURED",
                           "impact_scope": "graph_lookup", "created": created,
                           "candidates": len(self._index_candidates), "backend": "falkordb"})
        return created
