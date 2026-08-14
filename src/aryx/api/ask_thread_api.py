"""Aryx Ask endpoints backed by Shay channel/thread/message storage."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aryx.api.ask_api import AskRequest, Turn, _validate_workspace, run_ask
from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.store.ask_thread_store import AryxAskThreadStore

logger = logging.getLogger(__name__)
OCI_UNSUPPORTED_DETAIL = (
    "Shay-backed Ask threads are not available with the OCI database backend."
)


class AskThreadMessageRequest(BaseModel):
    workspace_id: int = 1
    shay_workspace_id: str
    thread_id: str
    request_id: str
    question: str
    session_data: dict[str, Any] = Field(default_factory=dict)


def _store_or_unsupported() -> AryxAskThreadStore:
    settings = get_settings()
    if settings.effective_db_backend() == "oci":
        raise HTTPException(501, OCI_UNSUPPORTED_DETAIL)
    return AryxAskThreadStore(settings.effective_dsn())


def _is_replayable_response(response: dict[str, Any] | None) -> bool:
    """Return whether a cached response represents a completed Ask run."""
    return bool(response) and not bool(response.get("error"))


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
        return str(exc)
    return ""


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
        store = _store_or_unsupported()
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
        store = _store_or_unsupported()
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

        store = _store_or_unsupported()
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
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ask run failed thread_id=%s request_id=%s elapsed_s=%.3f: %s",
                    req.thread_id, req.request_id, time.monotonic() - _t0, exc,
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
