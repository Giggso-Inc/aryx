"""Thin HTTP client helpers the MCP server uses to call the Aryx REST API.

Split out of `mcp/server.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

_API_URL = os.environ.get("ARYX_API_URL", "http://localhost:8088").rstrip("/")
_POST_TIMEOUT = int(os.environ.get("ARYX_MCP_POST_TIMEOUT", "50"))


def _get(path: str) -> Any:
    url = f"{_API_URL}{path}"
    with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _post(path: str, body: dict) -> Any:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{_API_URL}{path}", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_POST_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode())
