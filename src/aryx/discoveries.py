"""In-memory store of document-discovery results awaiting user confirmation.

The read step extracts mentions and stashes them here keyed by a discovery id;
the confirm step retrieves and ingests the user-approved subset. Process memory
only — nothing is written to disk.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_STORE: dict[str, dict[str, Any]] = {}


def put(discovery_id: str, data: dict[str, Any]) -> None:
    """Store a discovery result."""
    _STORE[discovery_id] = data
    logger.info("discoveries.put did=%s mentions=%d tabular=%d store_size=%d",
                discovery_id, len(data.get("mentions", [])), len(data.get("tabular", [])),
                len(_STORE))


def get(discovery_id: str) -> dict[str, Any] | None:
    """Return a discovery result, or None if unknown/expired."""
    data = _STORE.get(discovery_id)
    if data is None:
        logger.warning("discoveries.get did=%s not found (unknown or expired)", discovery_id)
    return data


def drop(discovery_id: str) -> None:
    """Forget a discovery result."""
    existed = _STORE.pop(discovery_id, None) is not None
    if existed:
        logger.info("discoveries.drop did=%s", discovery_id)
