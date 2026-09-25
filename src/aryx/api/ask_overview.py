"""Workspace overview used by the Ask flow.

A compact text block that ALWAYS rides along in the synthesis prompt so the
model can describe what's in the workspace even when a specific entity isn't
matched. Three blocks: kinds + counts + samples, declared relationship types,
and the workspace aim from the brief.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.graph import GraphReader
from aryx.store.relationship_type_store import RelationshipTypeStore
from aryx.workspaces import make_workspace_store

logger = logging.getLogger(__name__)


def build(reader: GraphReader, workspace_id: int) -> str:
    """Return a multi-line overview string. Best-effort; never raises."""
    parts: list[str] = ["WORKSPACE OVERVIEW:"]
    parts.extend(_kinds(reader))
    parts.extend(_relationships(workspace_id))
    parts.extend(_aim(workspace_id))
    return "\n".join(parts)


def _kinds(reader: GraphReader) -> list[str]:
    """List every entity type with its TRUE count + 3 sample names.

    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: previously grouped a single
    find_entities(limit=500) scan by type, so both the type list and the
    per-type counts silently went wrong on any workspace with more than 500
    entities (missing types entirely, under-counting the ones that did show
    up).

    T11 follow-up (real-data testing against workspace 704, 2026-09-25): the
    first fix for this called count_entities(t) + find_entities(ontology_
    type=t, limit=3) once per distinct type via distinct_types() -- correct,
    but measured at ~276s against a 109-type/204k-entity real workspace,
    because build() (which calls this) runs on every non-quote /ask turn.
    type_overview() replaces that up-to-218-round-trip loop with one grouped
    query (two on the Oracle backend), same output shape.
    """
    try:
        overview = reader.type_overview(sample_limit=3)
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview kinds skipped: %s", exc)
        return []
    if not overview:
        return []
    lines = ["Kinds tracked:"]
    for t in sorted(overview):
        info = overview[t]
        samples = [n for n in info.get("samples", []) if n]
        eg = f"  (e.g. {', '.join(samples)})" if samples else ""
        lines.append(f"  - {t}: {info.get('count', 0)} records{eg}")
    return lines


def _relationships(workspace_id: int) -> list[str]:
    """List declared relationship types from the W2 endpoint store."""
    try:
        rels = RelationshipTypeStore(get_settings().effective_dsn()).list(workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview rels skipped: %s", exc)
        return []
    if not rels:
        return []
    lines = ["Declared connections:"]
    for r in rels:
        lines.append(f"  - {r['source_type']} -[{r['name']}]-> "
                     f"{r['target_type']}")
    return lines


def _aim(workspace_id: int) -> list[str]:
    """Pull the aim line from the workspace brief, if set."""
    try:
        store = make_workspace_store(get_settings().effective_dsn())
        try:
            for w in store.list_all():
                if int(w.get("id", 0)) == int(workspace_id):
                    brief: dict[str, Any] = w.get("brief") or {}
                    aim = str(brief.get("aim") or "").strip()
                    return [f"Aim: {aim}"] if aim else []
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview aim skipped: %s", exc)
    return []
