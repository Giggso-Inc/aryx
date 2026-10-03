"""Request model + persistence helpers for the Ask-thread API.

Split out of `api/ask_thread_api.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03) — these only take `store`/`response` as parameters, never
calling the module-level `AryxAskThreadStore`/`run_ask`/`_validate_workspace`
names that `tests/test_ask_thread_api.py` patches, so they carry zero
patch risk. See `ask_thread_api.py`'s docstring for why the router itself
stays put.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from aryx.raven_log import raven_log
from aryx.store.ask_thread_store import AryxAskThreadStore

logger = logging.getLogger(__name__)


class AskThreadMessageRequest(BaseModel):
    workspace_id: int = 1
    shay_workspace_id: str
    thread_id: str
    request_id: str
    question: str
    session_data: dict[str, Any] = Field(default_factory=dict)


def _is_replayable_response(response: dict[str, Any] | None) -> bool:
    """Return whether a cached response represents a completed Ask run."""
    replayable = bool(response) and not bool(response.get("error"))
    raven_log("DEBUG", "P4", "ask.replay.checked cached response checked", context={
        "cached_found": bool(response), "replayable": replayable,
        "has_error": bool(response and response.get("error")),
    })
    return replayable


def _release_failed_request_after_persist_error(
    store: AryxAskThreadStore,
    thread_id: str,
    request_id: str,
) -> str:
    """Release a failed Ask run, returning an error if the status write fails."""
    try:
        store.mark_request_retryable(thread_id, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask request retry release failed: %s", exc)
        raven_log(
            "WARN", "P2", "ask.persist.failed retry release failed",
            error_code="ARYX_ASK_PERSIST_FAILED",
            context={"dependency_name": "adb", "operation": "release",
                     "result": "error", "error_class": type(exc).__name__,
                     "attempt": 1, "thread_id": thread_id, "request_id": request_id},
        )
        return str(exc)
    return ""


def _complete_request_after_success(
    store: AryxAskThreadStore,
    thread_id: str,
    request_id: str,
) -> str:
    """Close a successful request before persisting its assistant response."""
    try:
        store.mark_request_completed(thread_id, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask request completion persist failed: %s", exc)
        raven_log(
            "WARN", "P2", "ask.persist.failed request completion failed",
            error_code="ARYX_ASK_PERSIST_FAILED",
            context={"dependency_name": "adb", "operation": "complete",
                     "result": "error", "error_class": type(exc).__name__,
                     "attempt": 1, "thread_id": thread_id, "request_id": request_id},
        )
        return str(exc)
    return ""
