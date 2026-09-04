"""Shared in-memory sid→bearer-token store and payload encoding used across
the odoo_connect route package.

Bearer tokens captured from MCP's initiate call, keyed by sid → (token,
created_at). Used by the complete endpoint to call the orchestrator with
the user's own token.
"""

import base64
import json
import re
import time

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

_TOKEN_TTL_S: int = 600
_sid_token_store: dict[str, tuple[str, float]] = {}


def _prune_token_store() -> None:
    """Remove entries older than _TOKEN_TTL_S seconds."""
    cutoff = time.monotonic() - _TOKEN_TTL_S
    stale = [sid for sid, (_, ts) in _sid_token_store.items() if ts < cutoff]
    for sid in stale:
        _sid_token_store.pop(sid, None)


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as zoho_connect."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")
