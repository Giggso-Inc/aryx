"""Post-resolution enrichment helpers: type ancestors + relate stage.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the relate
stages live in dedicated sibling modules -- `pipeline.enrich_drain` (the
shared bounded-wait primitive), `pipeline.enrich_relate` (the best-effort
pairwise stage), `pipeline.enrich_relate_isolated` (the safety-net stage),
and `pipeline.enrich_schema_fk` (schema-level FK inference). Every name is
re-exported below so `orchestrate.py`'s existing import and
`tests/test_relate_resilience.py`'s direct calls keep working unchanged.
`_build_type_ancestors` stays here since it's the one function with no
relate-stage coupling.
"""
from __future__ import annotations

import logging

from aryx.pipeline.enrich_drain import _drain_with_timeout
from aryx.pipeline.enrich_relate import _relate
from aryx.pipeline.enrich_relate_isolated import _relate_isolated
from aryx.pipeline.enrich_schema_fk import _infer_schema_fk_links
from aryx.store.ontology_store import OntologyStore

__all__ = [
    "_build_type_ancestors",
    "_drain_with_timeout",
    "_infer_schema_fk_links",
    "_relate",
    "_relate_isolated",
]

logger = logging.getLogger(__name__)


def _build_type_ancestors(dsn: str, workspace_id: int = 1) -> dict[str, list[str]]:
    """Resolve ancestor chains for every declared type via OntologyStore."""
    ostore = OntologyStore(dsn, workspace_id)
    try:
        types = ostore.list_types()
        out: dict[str, list[str]] = {}
        for t in types:
            if t.parent_type:
                out[t.name] = ostore.ancestors(t.name)
        return out
    except Exception as exc:  # noqa: BLE001 — hierarchy is additive, never block projection
        logger.warning("type ancestors lookup failed; projecting without labels: %s", exc)
        return {}
    finally:
        ostore.close()
