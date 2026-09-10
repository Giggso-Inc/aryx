"""Entity/graph-browse calls for the Streamlit UI's Aryx REST client.

Split out of `ui/api.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero patch risk — see `api_http.py`'s docstring.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from aryx.ui.api_http import _WS, _delete, _get, _put


def get_entity_pg(entity_id: int) -> dict[str, Any]:
    """Fetch full entity record (id, ontology_type, attributes) from Postgres."""
    return _get(f"/admin/entities/{entity_id}")


def delete_entity(entity_id: int) -> dict[str, Any]:
    """Delete entity from Postgres + FalkorDB."""
    return _delete(f"/admin/entities/{entity_id}?workspace_id={_WS['id']}")


def update_entity(entity_id: int, attributes: dict) -> dict[str, Any]:
    """Replace entity attributes in Postgres and resync FalkorDB node."""
    return _put(f"/admin/entities/{entity_id}?workspace_id={_WS['id']}",
                {"attributes": attributes})


def full_graph() -> dict[str, Any]:
    return _get("/graph")


def search_entities(name: str = "", etype: str = "") -> list[dict]:
    params = []
    if name:
        params.append(f"name={urllib.parse.quote(name)}")
    if etype:
        params.append(f"type={urllib.parse.quote(etype)}")
    qs = "?" + "&".join(params) if params else ""
    return _get(f"/entities{qs}")


def get_neighbors(entity_id: int) -> list[dict]:
    return _get(f"/entities/{entity_id}/neighbors")


def get_provenance(entity_id: int) -> list[dict]:
    return _get(f"/entities/{entity_id}/provenance")


def get_path(src: int, dst: int) -> list[dict]:
    return _get(f"/entities/{src}/path/{dst}")
