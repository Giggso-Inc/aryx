"""Resolve a salesperson identity from trusted ingress headers."""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any, MutableMapping


def resolve_actor_id(
    headers: Any,
    session_state: MutableMapping[str, Any],
    query_params: MutableMapping[str, Any] | None = None,
) -> str:
    """Return an opaque actor id without using Aryx credentials.

    Production uses a trusted SSO header injected by ingress. An anonymous,
    session-scoped actor is available only through an explicit local override.

    st.session_state alone does not reliably survive a full page reload
    (e.g. behind a reverse proxy where the WebSocket session drops), which
    silently orphaned every prior chat under a fresh random actor id on
    refresh. When query_params is supplied, the same session-scoped id is
    also persisted there and re-read on the next load, so a reload of the
    same URL keeps the same anonymous actor instead of minting a new one.
    """
    header_name = os.environ.get(
        "ARYX_SALES_ACTOR_HEADER",
        "X-Forwarded-Email",
    )
    value = ""
    try:
        value = str(headers.get(header_name) or "").strip()
    except (AttributeError, TypeError):
        value = ""
    if value:
        digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()
        return f"sso:{digest}"
    if os.environ.get("ARYX_SALES_ALLOW_SESSION_ACTOR", "0") != "1":
        raise RuntimeError(
            f"Trusted sales identity header {header_name!r} was not provided"
        )
    key = "_aryx_sales_actor_id"
    if key in session_state:
        return str(session_state[key])
    token = ""
    if query_params is not None:
        try:
            token = str(query_params.get("actor") or "").strip()
        except (AttributeError, TypeError):
            token = ""
    if not token:
        token = str(uuid.uuid4())
    actor_id = f"session:{token}"
    session_state[key] = actor_id
    if query_params is not None:
        try:
            query_params["actor"] = token
        except (AttributeError, TypeError):
            pass
    return actor_id
