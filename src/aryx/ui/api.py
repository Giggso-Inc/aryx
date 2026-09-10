"""Thin HTTP client over the Aryx REST API for the Streamlit UI.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`api_http.py` (low-level HTTP verbs), `api_workspaces.py`
(workspace-scoped calls), and `api_entities.py` (entity/graph-browse
calls), all re-imported here. `tests/test_ui_api_client.py` patches
`aryx.ui.api.urllib.request.urlopen`, but since `urllib.request` is a
real stdlib module, that patch works via the shared module object
regardless of which file calls `urlopen` — zero patch risk from
splitting (confirmed via grep + this reasoning, not a bound-name
gotcha). `list_runs`/`list_jobs`/`get_job`/`ask`/`share_config`/
`get_llm_config`/`set_llm_config`/`observability` stay here.

`import urllib.request` below is otherwise unused directly in this file
— kept so `unittest.mock.patch`'s dotted-path resolution
(`aryx.ui.api.urllib.request.urlopen`) finds `urllib` as this module's
own attribute; without it, `patch()` raises `ModuleNotFoundError`
attempting to import a nonexistent `aryx.ui.api.urllib` submodule.
"""
from __future__ import annotations

import urllib.request  # noqa: F401 — see docstring: required for patch() dotted-path lookup
from typing import Any

from aryx.ui.api_entities import (
    delete_entity,
    full_graph,
    get_entity_pg,
    get_neighbors,
    get_path,
    get_provenance,
    search_entities,
    update_entity,
)
from aryx.ui.api_http import _get, _post
from aryx.ui.api_workspaces import (
    create_workspace,
    current_workspace,
    delete_workspace,
    list_workspaces,
    nuke_system,
    purge_workspace,
    set_workspace,
    set_workspace_brief,
    set_workspace_context,
)

__all__ = [
    "ask",
    "create_workspace",
    "current_workspace",
    "delete_entity",
    "delete_workspace",
    "full_graph",
    "get_entity_pg",
    "get_job",
    "get_llm_config",
    "get_neighbors",
    "get_path",
    "get_provenance",
    "list_jobs",
    "list_runs",
    "list_workspaces",
    "nuke_system",
    "observability",
    "purge_workspace",
    "search_entities",
    "set_llm_config",
    "set_workspace",
    "set_workspace_brief",
    "set_workspace_context",
    "share_config",
    "update_entity",
]


def list_runs() -> list[dict]:
    return _get("/admin/runs")


def list_jobs() -> list[dict]:
    return _get("/admin/jobs")


def get_job(job_id: str) -> dict[str, Any]:
    return _get(f"/admin/jobs/{job_id}")


def ask(question: str, history: list[dict] | None = None,
        session_data: dict | None = None) -> dict[str, Any]:
    return _post("/ask", {"question": question, "history": history or [],
                          "session_data": session_data or {}}, timeout=180)


def share_config(conversation_id: str, config_json: dict, endpoint_url: str,
                 auth_header_name: str = "Authorization", auth_header_value: str = "") -> dict[str, Any]:
    """POST the current CPQ config payload to a caller-supplied partner endpoint.

    Streamlit talks to the Aryx API directly (no Next.js proxy stripping the
    /api prefix), so this hits /share-config, not /api/share-config.
    """
    return _post("/share-config", {
        "conversation_id": conversation_id,
        "config_json": config_json,
        "endpoint_url": endpoint_url,
        "auth_header_name": auth_header_name,
        "auth_header_value": auth_header_value,
    }, timeout=30)


def get_llm_config() -> dict[str, Any]:
    return _get("/llm/config")


def set_llm_config(cfg: dict) -> dict[str, Any]:
    return _post("/admin/llm/config", cfg)


def observability() -> dict[str, Any]:
    return _get("/admin/observability")
