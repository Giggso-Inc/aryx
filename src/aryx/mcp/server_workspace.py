"""Workspace card enrichment for the MCP "list" tool.

Split out of `mcp/server.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from aryx.mcp.server_http import _get


def _enrich_workspace(ws: dict) -> dict:
    """Add entity/relationship counts + type breakdown for one workspace."""
    wid = int(ws.get("id", 1))
    try:
        types_doc = _get(f"/ontology/types?workspace_id={wid}") or {}
    except Exception as exc:  # noqa: BLE001
        return {
            "id": wid, "name": ws.get("name", ""),
            "description": ws.get("description", ""),
            "brief": ws.get("brief", {}),
            "entity_count": 0, "relationship_count": 0,
            "entity_types": [], "relationship_types": [],
            "axiom_count": 0, "axiom_kinds": {},
            "stats_error": str(exc),
        }
    axiom_count, axiom_kinds = _axiom_summary(wid)

    def _norm(items: list, key: str) -> list[dict]:
        out: list[dict] = []
        for t in items or []:
            if isinstance(t, dict):
                out.append({"name": t.get("name") or t.get("type") or "",
                            "count": int(t.get(key) or t.get("count") or 0)})
            else:
                out.append({"name": str(t), "count": 0})
        return [t for t in out if t["name"]]
    ents = _norm(types_doc.get("types") or types_doc.get("entity_types"),
                 "instance_count")
    rels = _norm(types_doc.get("relationships")
                 or types_doc.get("relationship_types"), "count")
    return {
        "id": wid,
        "name": ws.get("name", ""),
        "description": ws.get("description", ""),
        "brief": ws.get("brief", {}),
        "entity_count": int(types_doc.get("entity_count")
                            or sum(t["count"] for t in ents)),
        "relationship_count": sum(t["count"] for t in rels),
        "entity_types": ents,
        "relationship_types": rels,
        "axiom_count": axiom_count,
        "axiom_kinds": axiom_kinds,
    }


def _axiom_summary(workspace_id: int) -> tuple[int, dict]:
    try:
        doc = _get(f"/ontology/axioms?workspace_id={workspace_id}") or {}
    except Exception:  # noqa: BLE001 — axioms advisory in MCP card
        return 0, {}
    axioms = doc.get("axioms") or []
    kinds: dict[str, int] = {}
    for ax in axioms:
        if k := str(ax.get("kind") or ""):
            kinds[k] = kinds.get(k, 0) + 1
    return len(axioms), kinds
