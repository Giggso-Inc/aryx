"""Sales-scoped MCP facade over Aryx Ask and Shay-backed conversations."""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable

from aryx.api.ask_api import AskRequest, Turn, _cpq_engine, _reader, run_ask
from aryx.config import get_settings
from aryx.mcp.auth import McpPrincipal
from sales_streamlit.chat_store import SalesChatStore

_ACTOR_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,255}$")


def _validated_actor(actor_id: Any) -> str:
    """Validate and normalize the application-supplied salesperson identity."""
    value = str(actor_id or "").strip()
    if not _ACTOR_PATTERN.fullmatch(value):
        raise ValueError("actor_id is required and must be at most 255 characters")
    return value


def _validated_uuid(value: Any, field: str) -> str:
    """Validate an externally supplied UUID field."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


class SalesChatService:
    """Invoke Aryx Ask within a token-bound workspace and actor boundary."""

    def __init__(
        self,
        principal: McpPrincipal,
        *,
        store: SalesChatStore | None = None,
        ask_runner: Callable[[AskRequest], dict[str, Any]] = run_ask,
    ) -> None:
        """Bind the service to one authenticated MCP principal."""
        if not principal.is_sales_cpq:
            raise PermissionError("A sales_cpq MCP token is required")
        if principal.workspace_id is None or not principal.shay_workspace_id:
            raise PermissionError("Sales MCP token is missing its workspace binding")
        self._principal = principal
        self._store = store or SalesChatStore(get_settings().effective_dsn())
        self._ask_runner = ask_runner

    @property
    def workspace_id(self) -> int:
        """Return the token-bound Aryx workspace."""
        return int(self._principal.workspace_id or 0)

    @property
    def shay_workspace_id(self) -> str:
        """Return the token-bound hidden Shay workspace."""
        return str(self._principal.shay_workspace_id or "")

    def close(self) -> None:
        """Release service resources managed outside the shared pool."""
        self._store.close()

    def start(self, actor_id: Any) -> dict[str, Any]:
        """Allocate and actor-bind a new sales conversation thread."""
        actor = _validated_actor(actor_id)
        thread_id = str(uuid.uuid4())
        self._store.claim_thread(
            thread_id=thread_id,
            actor_id=actor,
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
        )
        return {"ok": True, "thread_id": thread_id}

    def list_threads(self, actor_id: Any, limit: int = 50) -> dict[str, Any]:
        """List only conversations owned by the actor."""
        actor = _validated_actor(actor_id)
        return {
            "ok": True,
            "threads": self._store.list_threads(
                actor_id=actor,
                workspace_id=self.workspace_id,
                shay_workspace_id=self.shay_workspace_id,
                limit=limit,
            ),
        }

    def get_messages(
        self,
        actor_id: Any,
        thread_id: Any,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Load one actor-owned transcript."""
        actor = _validated_actor(actor_id)
        thread = _validated_uuid(thread_id, "thread_id")
        return {
            "ok": True,
            "thread_id": thread,
            "messages": self._store.list_messages(
                thread_id=thread,
                actor_id=actor,
                workspace_id=self.workspace_id,
                shay_workspace_id=self.shay_workspace_id,
                limit=limit,
            ),
        }

    def send(
        self,
        *,
        actor_id: Any,
        thread_id: Any,
        request_id: Any,
        message: Any,
    ) -> dict[str, Any]:
        """Persist, execute, and return one idempotent Aryx Ask turn."""
        actor = _validated_actor(actor_id)
        thread = _validated_uuid(thread_id, "thread_id")
        request = _validated_uuid(request_id, "request_id")
        question = str(message or "").strip()
        if not question or len(question) > 20_000:
            raise ValueError("message is required and must be at most 20000 characters")
        self._claim(actor, thread)
        ask_store = self._store.ask
        cached = ask_store.get_completed_response(
            self.shay_workspace_id,
            thread,
            request,
        )
        if cached and not cached.get("error"):
            return self._decorate(cached, thread, request, replayed=True)

        session_data = self._latest_session(actor, thread)
        saved = ask_store.ensure_thread_and_user_message(
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
            thread_id=thread,
            request_id=request,
            question=question,
        )
        if not saved.get("request_claimed", True):
            cached = ask_store.get_completed_response(
                self.shay_workspace_id,
                thread,
                request,
            )
            if cached and not cached.get("error"):
                return self._decorate(cached, thread, request, replayed=True)
            raise RuntimeError("This sales chat request is already being processed")
        result = self._run(question, thread, request, session_data)
        self._persist(thread, request, saved["channel_id"], result)
        return self._decorate(result, thread, request, replayed=False)

    def _claim(self, actor: str, thread: str) -> None:
        """Claim a new thread or revalidate its immutable actor scope."""
        self._store.claim_thread(
            thread_id=thread,
            actor_id=actor,
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
        )

    def _latest_session(self, actor: str, thread: str) -> dict[str, Any]:
        """Load server-side CPQ state from the latest assistant message."""
        latest = self._store.latest_assistant(
            thread_id=thread,
            actor_id=actor,
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
        )
        return (latest or {}).get("session_data") or {}

    def _run(
        self,
        question: str,
        thread: str,
        request: str,
        session_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Aryx Ask and normalize an execution failure."""
        try:
            history = [
                Turn(role=entry["role"], text=entry["text"])
                for entry in self._store.ask.conversation_history(thread, request)
            ]
            return self._ask_runner(
                AskRequest(
                    question=question,
                    history=history,
                    workspace_id=self.workspace_id,
                    session_data=session_data,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "answer": "Aryx could not complete this response. Please try again.",
                "terms": [],
                "tools_called": [],
                "usage": {},
                "grounding": None,
                "session_data": session_data,
                "cpq_payload": None,
                "error": str(exc),
            }

    def _persist(
        self,
        thread: str,
        request: str,
        channel_id: str,
        result: dict[str, Any],
    ) -> None:
        """Persist the assistant turn and its idempotency completion state."""
        if not result.get("error"):
            self._store.ask.mark_request_completed(thread, request)
        saved = self._store.ask.append_assistant_message(
            thread_id=thread,
            channel_id=channel_id,
            request_id=request,
            answer=str(result.get("answer") or ""),
            result=result,
        )
        result["assistant_message_id"] = saved["assistant_message_id"]
        result["citations"] = saved.get("citations") or []

    def confirm(
        self,
        *,
        actor_id: Any,
        thread_id: Any,
        message_id: Any,
        request_id: Any,
    ) -> dict[str, Any]:
        """Confirm the relevant awaiting-approval message and return MSI input."""
        actor = _validated_actor(actor_id)
        thread = _validated_uuid(thread_id, "thread_id")
        expected_message = _validated_uuid(message_id, "message_id")
        latest = self._store.latest_assistant(
            thread_id=thread,
            actor_id=actor,
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
        )
        if latest is None or latest["id"] != expected_message:
            raise ValueError("Only the latest assistant message can be confirmed")
        status = str((latest.get("session_data") or {}).get("status") or "")
        if status not in {"awaiting_approval", "post_approval"}:
            raise ValueError("The selected message is not awaiting confirmation")

        result = self.send(
            actor_id=actor,
            thread_id=thread,
            request_id=request_id,
            message="confirm",
        )
        payload = result.get("cpq_payload") or {}
        config_data = payload.get("configData")
        if not isinstance(config_data, dict):
            return {
                **result,
                "confirmed": False,
                "message": (
                    "Aryx did not produce configData. Review the updated "
                    "assistant response before confirming again."
                ),
            }
        route = self._product_route(result.get("session_data") or {})
        return {
            **result,
            "confirmed": True,
            "confirmation_id": result["assistant_message_id"],
            "configData": config_data,
            "product_context": route,
        }

    def resolve_route(self, actor_id: Any, thread_id: Any) -> dict[str, Any]:
        """Read-only BmCatalog route lookup for an already-confirmed payload.

        Unlike confirm(), this never re-runs the CPQ turn or its stale-
        constraint gate — it only resolves family/line/model from the
        latest assistant message's own session_data, for callers that
        already hold a build_payload()-shaped configData client-side
        (e.g. the Streamlit awaiting_approval preview) and just need the
        MSI route to drive the workflow directly.
        """
        actor = _validated_actor(actor_id)
        thread = _validated_uuid(thread_id, "thread_id")
        latest = self._store.latest_assistant(
            thread_id=thread,
            actor_id=actor,
            workspace_id=self.workspace_id,
            shay_workspace_id=self.shay_workspace_id,
        )
        if latest is None:
            raise ValueError("No assistant message found for this thread")
        route = self._product_route(latest.get("session_data") or {})
        return {"ok": True, "product_context": route}

    def _product_route(self, session_data: dict[str, Any]) -> dict[str, str]:
        """Resolve the confirmed configuration's validated BmCatalog route."""
        # single_model_variable_name/model_catalog_path key off the
        # ontology_type prefix (e.g. "ApxNextConfig"), not the human
        # product_name ("aSTRO25_bom"). CpqSession.catalog_prefix is never
        # actually assigned anywhere in ask_api.py — every call site there
        # derives it fresh per-turn as `attrs[0].catalog_prefix`, so it must
        # be re-derived here the same way rather than read off session_data.
        product_name = str(session_data.get("product_name") or "").strip()
        filled = session_data.get("filled") or {}
        model = str(filled.get("_bm_model_variable_name") or "").strip()
        reader = _reader(self.workspace_id)
        if not product_name:
            raise ValueError("Aryx configuration has no resolved product")
        attrs, _ = _cpq_engine.load_product_config(
            reader, self.workspace_id, product_name,
        )
        catalog_prefix = attrs[0].catalog_prefix if attrs else ""
        if not catalog_prefix:
            raise ValueError(
                "Aryx configuration has no resolved catalog prefix"
            )
        if not model:
            model = _cpq_engine.single_model_variable_name(
                reader,
                self.workspace_id,
                catalog_prefix,
            )
        if not model:
            raise ValueError(
                "Aryx configuration has no unambiguous BmCatalog model leaf"
            )
        return _cpq_engine.model_catalog_path(
            reader,
            self.workspace_id,
            catalog_prefix,
            model,
            product_family=product_name,
        )

    @staticmethod
    def _decorate(
        result: dict[str, Any],
        thread_id: str,
        request_id: str,
        *,
        replayed: bool,
    ) -> dict[str, Any]:
        """Add transport metadata and the message-specific confirm flag."""
        session = result.get("session_data") or {}
        message_id = str(result.get("assistant_message_id") or "")
        return {
            **result,
            "ok": not bool(result.get("error")),
            "thread_id": thread_id,
            "request_id": request_id,
            "assistant_message_id": message_id,
            "show_confirm": (
                str(session.get("status") or "") == "awaiting_approval"
                and bool(message_id)
            ),
            "replayed": replayed,
        }
