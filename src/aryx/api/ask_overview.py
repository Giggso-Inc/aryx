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
    up). distinct_types() + count_entities(t) are each deterministic, no
    sampling — same reasoning distinct_types()'s own docstring already gives
    for why find_entities(limit=N) can't be used to discover types either.
    """
    try:
        types = reader.distinct_types()
    except Exception as exc:  # noqa: BLE001
        logger.debug("overview kinds skipped: %s", exc)
        return []
    if not types:
        return []
    lines = ["Kinds tracked:"]
    for t in sorted(types):
        try:
            count = reader.count_entities(t)
            samples = [e.get("name", "") for e in reader.find_entities(ontology_type=t, limit=3)]
        except Exception as exc:  # noqa: BLE001
            logger.debug("overview kind %s skipped: %s", t, exc)
            continue
        samples = [n for n in samples if n]
        eg = f"  (e.g. {', '.join(samples)})" if samples else ""
        lines.append(f"  - {t}: {count} records{eg}")
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
