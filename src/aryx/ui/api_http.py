"""Low-level HTTP verbs for the Streamlit UI's Aryx REST client.

Split out of `ui/api.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). `urllib.request.urlopen` is patched by
`tests/test_ui_api_client.py`, but as a real stdlib module attribute
that patch works via the shared `urllib.request` module object
regardless of which file calls it — zero patch risk from splitting.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

_BASE = os.environ.get("ARYX_API_URL", "http://localhost:8088").rstrip("/")

_WS = {"id": 1}


def _get(path: str) -> Any:
    """GET a path, appending the active workspace id, and decode JSON."""
    sep = "&" if "?" in path else "?"
    url = f"{_BASE}{path}{sep}workspace_id={_WS['id']}"
    with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def _post(path: str, body: dict, timeout: int = 30) -> Any:
    """POST a JSON body (merged with the workspace id) and decode the reply."""
    data = json.dumps({"workspace_id": _WS["id"], **body}).encode()
    req = urllib.request.Request(
        f"{_BASE}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read())


def _post_raw(path: str, body: bytes = b"{}", timeout: int = 30) -> Any:
    req = urllib.request.Request(
        f"{_BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read())


def _delete(path: str) -> Any:
    req = urllib.request.Request(f"{_BASE}{path}", method="DELETE")
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())


def _put(path: str, body: dict) -> Any:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{_BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="PUT",
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        return json.loads(r.read())
