"""Workspace-scoped calls for the Streamlit UI's Aryx REST client.

Split out of `ui/api.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero patch risk — see `api_http.py`'s docstring.
"""
from __future__ import annotations

import json
import urllib.request

from aryx.ui.api_http import _BASE, _WS, _delete, _get, _post, _post_raw


def set_workspace(workspace_id: int) -> None:
    """Set the active workspace for all subsequent scoped calls."""
    _WS["id"] = int(workspace_id)


def current_workspace() -> int:
    """Return the id of the currently selected workspace."""
    return _WS["id"]


def list_workspaces() -> list[dict]:
    return _get("/admin/workspaces")


def create_workspace(name: str, description: str = "", context: str = "") -> dict:
    return _post("/admin/workspaces",
                 {"name": name, "description": description, "context": context})


def delete_workspace(workspace_id: int) -> dict:
    return _delete(f"/admin/workspaces/{workspace_id}")


def purge_workspace(workspace_id: int) -> dict:
    return _post_raw(f"/admin/workspaces/{workspace_id}/purge", timeout=60)


def nuke_system() -> dict:
    return _post_raw("/admin/workspaces/nuke", timeout=120)


def set_workspace_context(workspace_id: int, context: str) -> dict:
    data = json.dumps({"context": context}).encode()
    req = urllib.request.Request(
        f"{_BASE}/admin/workspaces/{workspace_id}/context",
        data=data, headers={"Content-Type": "application/json"}, method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def set_workspace_brief(workspace_id: int, brief: dict) -> dict:
    data = json.dumps(brief).encode()
    req = urllib.request.Request(
        f"{_BASE}/admin/workspaces/{workspace_id}/brief",
        data=data, headers={"Content-Type": "application/json"}, method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())
