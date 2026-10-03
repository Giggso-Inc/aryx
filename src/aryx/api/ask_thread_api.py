"""Aryx Ask endpoints backed by Shay channel/thread/message storage.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03),
`AskThreadMessageRequest`/`_is_replayable_response`/
`_release_failed_request_after_persist_error`/
`_complete_request_after_success` moved to `ask_thread_helpers.py` (zero
patch risk — see that module's docstring). `_store`/`ask_thread_router`
stay here as a deliberate exception: `AryxAskThreadStore`/`run_ask`/
`_validate_workspace` are all directly whitebox-patched
(`aryx.api.ask_thread_api.*`) by `tests/test_ask_thread_api.py` and
called only from `_store()`/the router's route closures.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from aryx.api.ask_core_helpers import _validate_workspace
from aryx.api.ask_request_models import AskRequest, Turn
from aryx.api.ask_run_ask import current_road, current_step, run_ask
from aryx.raven_log import current_run_id, raven_log
from aryx.api.ask_thread_helpers import (
    AskThreadMessageRequest,
    _complete_request_after_success,
    _is_replayable_response,
    _release_failed_request_after_persist_error,
)
from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.store.ask_thread_store import AryxAskThreadStore

logger = logging.getLogger(__name__)

__all__ = ["AskThreadMessageRequest", "ask_thread_router"]


def _store() -> AryxAskThreadStore:
    """Return an Ask thread store for the configured backend.

    Works on both Postgres and OCI -- see docs/OCI_POSTGRES_PARITY_AUDIT.md
    for the Oracle port.
    """
    return AryxAskThreadStore(get_settings().effective_dsn())


def ask_thread_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_api_key)])

    @router.get("/ask/threads")
    def list_threads(
        workspace_id: int,
        shay_workspace_id: str,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        """List hidden Aryx Ask threads for the Shay workspace."""
        _validate_workspace(workspace_id)
        store = _store()
        try:
            return store.list_threads(workspace_id, shay_workspace_id, limit)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            store.close()

    @router.get("/ask/threads/{thread_id}/messages")
    def list_messages(
        thread_id: str,
        workspace_id: int,
        shay_workspace_id: str,
        before_sequence: int | None = Query(None, ge=1),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        """Fetch one Ask thread transcript without invoking Aryx Ask."""
        _validate_workspace(workspace_id)
        store = _store()
        try:
            return store.list_messages(
                workspace_id,
                shay_workspace_id,
                thread_id,
                before_sequence,
                limit,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            store.close()

    @router.post("/ask/threads/message")
    def submit_message(req: AskThreadMessageRequest) -> dict[str, Any]:
        """Persist a user prompt, run Aryx Ask once, then persist the response."""
        _validate_workspace(req.workspace_id)
        question = req.question.strip()
        if not question:
            raise HTTPException(422, "question is required")

        store = _store()
        try:
            try:
                store.validate_mapping(req.workspace_id, req.shay_workspace_id)
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc

            cached = store.get_completed_response(
                req.shay_workspace_id,
                req.thread_id,
                req.request_id,
            )
            if _is_replayable_response(cached):
                raven_log("INFO", "P4", "ask.turn.completed replayed cached response", context={
                    "final_status": "answered", "result": "ok", "reason_code": "replay",
                    "thread_id": req.thread_id, "request_id": req.request_id,
                    "workspace_id": req.workspace_id, "persisted": True,
                })
                return {
                    **cached,
                    "thread_id": req.thread_id,
                    "request_id": req.request_id,
                    "replayed": True,
                }

            try:
                saved = store.ensure_thread_and_user_message(
                    workspace_id=req.workspace_id,
                    shay_workspace_id=req.shay_workspace_id,
                    thread_id=req.thread_id,
                    request_id=req.request_id,
                    question=question,
                )
                if not saved.get("request_claimed", True):
                    cached = store.get_completed_response(
                        req.shay_workspace_id,
                        req.thread_id,
                        req.request_id,
                    )
                    if _is_replayable_response(cached):
                        return {
                            **cached,
                            "thread_id": req.thread_id,
                            "request_id": req.request_id,
                            "replayed": True,
                        }
                    raise HTTPException(
                        409,
                        "This Ask request is already being processed.",
                    )
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, HTTPException):
                    raise
                if isinstance(exc, ValueError):
                    raise HTTPException(409, str(exc)) from exc
                logger.warning("ask prompt persist failed: %s", exc)
                raven_log(
                    "WARN", "P2", "ask.persist.failed prompt persist failed",
                    error_code="ARYX_ASK_PERSIST_FAILED",
                    context={"dependency_name": "adb", "operation": "save_prompt",
                             "result": "error", "error_class": type(exc).__name__,
                             "attempt": 1, "thread_id": req.thread_id,
                             "request_id": req.request_id},
                )
                raise HTTPException(
                    503,
                    "Unable to save the prompt, so Aryx Ask was not called.",
                ) from exc

            # _t0 must be set BEFORE the try block -- the except clause below
            # references it unconditionally, and conversation_history() (the
            # first call inside try) can itself raise before _t0 would
            # otherwise be assigned, which previously turned a cleanly-handled
            # failure into an unhandled UnboundLocalError on this exact
            # endpoint (caught in PR #200 review).
            _t0 = time.monotonic()
            try:
                history = [
                    Turn(role=entry["role"], text=entry["text"])
                    for entry in store.conversation_history(req.thread_id, req.request_id)
                ]
                # Explicit start/elapsed markers around run_ask — this is the
                # one call in this endpoint that can silently block for
                # minutes (a hung LLM call has no intermediate log output of
                # its own), confirmed live 2026-08-14: a POST here took 15
                # min with zero cpq.engine/ask_api log lines in that window.
                logger.info(
                    "ask_run_start thread_id=%s request_id=%s workspace_id=%s",
                    req.thread_id, req.request_id, req.workspace_id,
                )
                result = run_ask(
                    AskRequest(
                        question=question,
                        history=history,
                        workspace_id=req.workspace_id,
                        session_data=req.session_data,
                    )
                )
                logger.info(
                    "ask_run_end thread_id=%s request_id=%s elapsed_s=%.3f",
                    req.thread_id, req.request_id, time.monotonic() - _t0,
                )
                _run_ms = int((time.monotonic() - _t0) * 1000)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ask run failed thread_id=%s request_id=%s elapsed_s=%.3f: %s",
                    req.thread_id, req.request_id, time.monotonic() - _t0, exc,
                )
                raven_log(
                    "ERROR", "P2", "ask.turn.failed ask run raised",
                    error_code="ARYX_ASK_RUN_FAILED",
                    context={"final_status": "failed", "result": "error",
                             "reason_code": type(exc).__name__,
                             "duration_ms": int((time.monotonic() - _t0) * 1000),
                             "last_step": current_step(), "road": current_road() or "unknown",
                             "thread_id": req.thread_id, "request_id": req.request_id,
                             "run_id": current_run_id(), "workspace_id": req.workspace_id},
                )
                answer = "Aryx Ask could not complete this response. Please try again."
                result = {
                    "answer": answer,
                    "terms": [],
                    "tools_called": [],
                    "usage": {},
                    "grounding": None,
                    "session_data": req.session_data,
                    "error": str(exc),
                }
                persistence_error = ""
                citations = []
                try:
                    saved_response = store.append_assistant_message(
                        thread_id=req.thread_id,
                        channel_id=saved["channel_id"],
                        request_id=req.request_id,
                        answer=answer,
                        result=result,
                    )
                    citations = saved_response.get("citations") or []
                except Exception as persist_exc:  # noqa: BLE001
                    logger.warning("ask failure response persist failed: %s", persist_exc)
                    raven_log(
                        "WARN", "P2", "ask.persist.failed failure response persist failed",
                        error_code="ARYX_ASK_PERSIST_FAILED",
                        context={"dependency_name": "adb", "operation": "save_response",
                                 "result": "error", "error_class": type(persist_exc).__name__,
                                 "attempt": 1, "thread_id": req.thread_id,
                                 "request_id": req.request_id},
                    )
                    persistence_error = str(persist_exc)
                    release_error = _release_failed_request_after_persist_error(
                        store,
                        req.thread_id,
                        req.request_id,
                    )
                    if release_error:
                        persistence_error += f"; retry release failed: {release_error}"
                return JSONResponse(
                    status_code=502,
                    content={
                        **result,
                        "thread_id": req.thread_id,
                        "request_id": req.request_id,
                        "replayed": False,
                        "citations": citations,
                        "persistence_error": persistence_error or None,
                    },
                )
            answer = result.get("answer", "") or ""
            completion_error = _complete_request_after_success(
                store,
                req.thread_id,
                req.request_id,
            )
            persistence_error = ""
            citations = []
            try:
                saved_response = store.append_assistant_message(
                    thread_id=req.thread_id,
                    channel_id=saved["channel_id"],
                    request_id=req.request_id,
                    answer=answer,
                    result=result,
                )
                citations = saved_response.get("citations") or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("ask response persist failed: %s", exc)
                raven_log(
                    "WARN", "P2", "ask.persist.failed response persist failed",
                    error_code="ARYX_ASK_PERSIST_FAILED",
                    context={"dependency_name": "adb", "operation": "save_response",
                             "result": "error", "error_class": type(exc).__name__,
                             "attempt": 1, "thread_id": req.thread_id,
                             "request_id": req.request_id},
                )
                persistence_error = str(exc)
                if completion_error:
                    completion_error = _complete_request_after_success(
                        store,
                        req.thread_id,
                        req.request_id,
                    )
                if completion_error:
                    persistence_error += (
                        f"; request completion failed: {completion_error}"
                    )

            _sd = result.get("session_data") if isinstance(result, dict) else None
            _sd = _sd if isinstance(_sd, dict) else {}
            raven_log("INFO", "P4", "ask.turn.completed turn finished", context={
                "final_status": _sd.get("status") or "answered", "result": "ok",
                "reason_code": current_road() or "unknown", "duration_ms": _run_ms,
                "thread_id": req.thread_id, "request_id": req.request_id,
                "run_id": _sd.get("run_id") or current_run_id(),
                "workspace_id": req.workspace_id,
                "persisted": not persistence_error, "answer_len": len(answer),
            })
            return {
                **result,
                "answer": answer,
                "thread_id": req.thread_id,
                "request_id": req.request_id,
                "replayed": False,
                "citations": citations,
                "persistence_error": persistence_error or None,
            }
        finally:
            store.close()

    return router
