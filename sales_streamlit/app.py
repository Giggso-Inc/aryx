"""Sales-facing Streamlit chat for Aryx-guided MSI configuration."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import streamlit as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from aryx.config import get_settings
from sales_streamlit.identity import resolve_actor_id
from sales_streamlit.mcp_client import SalesMcpClient, SalesMcpSettings
from sales_streamlit.msi_client import MsiCpqClient, MsiSettings
from sales_streamlit.msi_workflow import (
    MSI_STEP_NAMES,
    MsiWorkflowRequest,
    MsiWorkflowRunner,
)
from sales_streamlit.workflow_store import SalesMsiWorkflowStore

st.set_page_config(
    page_title="Sales Quote Assistant",
    page_icon="💬",
    layout="wide",
)


def _configured_workspaces() -> dict[str, str]:
    """Return {label: sales_cpq token} for every workspace this instance serves.

    Each token is scoped to exactly one workspace_id/shay_workspace_id at
    issuance (POST /admin/mcp/tokens) — there's no way to change a token's
    workspace after the fact, so switching workspaces in the UI means
    switching which pre-issued token this deployment uses, not passing a
    workspace_id through directly. ARYX_SALES_WORKSPACES holds a JSON
    object of label -> token for deployments serving more than one
    workspace; ARYX_SALES_MCP_API_KEY alone still works as a single
    "Default" entry for existing single-workspace deployments.
    """
    raw = os.environ.get("ARYX_SALES_WORKSPACES", "").strip()
    if not raw:
        single = os.environ.get("ARYX_SALES_MCP_API_KEY", "").strip()
        return {"Default": single} if single else {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ARYX_SALES_WORKSPACES must be valid JSON") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
    ):
        raise RuntimeError(
            "ARYX_SALES_WORKSPACES must be a JSON object of {label: token}"
        )
    return parsed


@st.cache_resource
def _mcp_client(api_key: str) -> SalesMcpClient:
    """Return the process-cached server-side Aryx MCP client for one workspace token."""
    return SalesMcpClient(SalesMcpSettings.from_env(api_key=api_key))


@st.cache_resource
def _msi_client() -> MsiCpqClient:
    """Return the process-cached direct MSI client."""
    return MsiCpqClient(MsiSettings.from_env())


@st.cache_resource
def _workflow_store() -> SalesMsiWorkflowStore:
    """Return the durable PostgreSQL MSI workflow store."""
    settings = get_settings()
    if settings.effective_db_backend() == "oci":
        raise RuntimeError("The sales chat workflow requires PostgreSQL")
    return SalesMsiWorkflowStore(settings.effective_dsn())


def _load_messages(client: SalesMcpClient, actor_id: str) -> list[dict[str, Any]]:
    """Load the active actor-owned transcript."""
    thread_id = st.session_state.get("sales_thread_id")
    if not thread_id:
        return []
    return client.get_messages(actor_id, thread_id)


def _show_workflow(message_id: str) -> bool:
    """Render any durable MSI workflow beneath its confirmation message."""
    workflow = _workflow_store().get_by_confirmation(message_id)
    if not workflow:
        return False
    state_icon = {"success": "✅", "error": "❌", "running": "⏳"}
    st.caption(
        f"{state_icon.get(workflow['status'], '•')} "
        f"MSI workflow: {workflow['status']}"
    )
    for step in workflow.get("steps") or []:
        icon = {
            "success": "✅",
            "error": "❌",
            "running": "⏳",
            "skipped": "⏭️",
            "pending": "○",
        }.get(step.get("status"), "○")
        label = str(step.get("name") or "").replace("_", " ").title()
        message = str(step.get("message") or "")
        st.caption(f"{icon} {label}" + (f" — {message}" if message else ""))
    return True


def _run_msi(confirmed: dict[str, Any], actor_id: str, thread_id: str) -> None:
    """Execute and display the direct nine-step MSI workflow."""
    route = confirmed.get("product_context") or {}
    request = MsiWorkflowRequest(
        confirmation_id=str(confirmed["confirmation_id"]),
        actor_id=actor_id,
        thread_id=thread_id,
        config_data=confirmed["configData"],
        product_family=str(route.get("product_family") or ""),
        product_line=str(route.get("product_line") or ""),
        model=str(route.get("model") or ""),
    )
    with st.status("Creating MSI quote transaction…", expanded=True) as status:
        placeholders = {name: st.empty() for name in MSI_STEP_NAMES}

        def on_step(workflow: dict[str, Any]) -> None:
            """Refresh the visible status line for each persisted step."""
            for step in workflow.get("steps") or []:
                icon = {
                    "success": "✅",
                    "error": "❌",
                    "running": "⏳",
                    "skipped": "⏭️",
                    "pending": "○",
                }.get(step.get("status"), "○")
                label = str(step.get("name") or "").replace("_", " ").title()
                placeholders[step["name"]].markdown(f"{icon} {label}")

        result = MsiWorkflowRunner(_msi_client(), _workflow_store()).run(
            request,
            on_step=on_step,
        )
        if result["status"] == "success":
            status.update(
                label="MSI quote transaction completed",
                state="complete",
                expanded=True,
            )
        else:
            status.update(
                label="MSI quote transaction stopped",
                state="error",
                expanded=True,
            )


def _confirm_message(
    client: SalesMcpClient,
    actor_id: str,
    thread_id: str,
    message_id: str,
    config_data: dict[str, Any],
) -> None:
    """Run MSI directly from the already-rendered configData.

    Deliberately does NOT call sales_chat_confirm — that re-runs the full
    CPQ turn (catalog reload + constraint recheck), which can re-flag an
    already-resolved stale-constraint attribute and loop instead of
    confirming. The salesperson has already seen and reviewed this exact
    payload in the JSON/Beautify preview; only the MSI-side product route
    (family/line/model) still needs a server lookup, via a read-only tool
    that never touches CPQ session state or its validation gate.
    """
    try:
        with st.spinner("Resolving MSI product route…"):
            resolved = client.resolve_route(actor_id, thread_id)
        confirmed = {
            "confirmation_id": message_id,
            "configData": config_data,
            "product_context": resolved.get("product_context") or {},
        }
        _run_msi(confirmed, actor_id, thread_id)
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))


def _is_latest_status(
    role: str,
    message_id: str,
    latest_assistant_id: str,
    session: dict[str, Any],
    status: str,
) -> bool:
    """Return whether this is the latest assistant message in a CPQ status."""
    return (
        role == "assistant"
        and message_id == latest_assistant_id
        and session.get("status") == status
    )


def _render_message(
    client: SalesMcpClient,
    actor_id: str,
    thread_id: str,
    message: dict[str, Any],
    latest_assistant_id: str,
) -> None:
    """Render one chat message and any action relevant to its CPQ state."""
    role = str(message.get("role") or "assistant")
    with st.chat_message(role):
        st.markdown(str(message.get("content") or ""))
        message_id = str(message.get("id") or "")
        session = message.get("session_data") or {}
        has_workflow = bool(
            message.get("cpq_payload") and _show_workflow(message_id)
        )
        is_complete_stage = session.get("status") in ("awaiting_approval", "post_approval")
        payload = message.get("cpq_payload")
        config_data = (payload or {}).get("configData") if payload else None
        if is_complete_stage and config_data:
            # Same configData/value/displayValue shape Aryx renders, at both
            # the awaiting_approval preview and the post-approval message.
            col_json, col_beautify = st.columns(2)
            with col_json:
                with st.expander("JSON"):
                    st.json(payload)
            with col_beautify:
                with st.expander("Beautify"):
                    attrs_out, values_out = [], []
                    for attr_name, entry in config_data.items():
                        if isinstance(entry, dict) and "value" in entry:
                            attrs_out.append(attr_name)
                            values_out.append(
                                str(entry.get("displayValue", entry["value"]))
                            )
                        elif isinstance(entry, dict) and "items" in entry:
                            attrs_out.append(attr_name)
                            values_out.append(
                                ", ".join(
                                    str(i.get("displayValue", i.get("value", "")))
                                    for i in entry["items"]
                                )
                            )
                        else:
                            attrs_out.append(attr_name)
                            values_out.append(str(entry))
                    # Arrow (Streamlit's table backend) rejects an object
                    # column mixing types (e.g. bool + str attribute
                    # values) — every value is stringified above so the
                    # Value column is always homogeneous.
                    st.table({"Attribute": attrs_out, "Value": values_out})
        elif is_complete_stage and session.get("filled"):
            # Fallback preview for any turn where the backend hasn't attached
            # a build_payload()-shaped cpq_payload yet — shows the raw,
            # unstructured in-progress session state instead. Gated on the
            # same completion status so intermediate clarifying questions
            # (e.g. the product-family prompt) never show a premature
            # preview built from a handful of auto-filled defaults.
            col_json, col_beautify = st.columns(2)
            with col_json:
                with st.expander("JSON"):
                    st.json(session["filled"])
            with col_beautify:
                with st.expander("Beautify"):
                    display_values = session.get("display_filled") or session["filled"]
                    st.table(
                        {
                            "Attribute": list(display_values.keys()),
                            "Value": [str(v) for v in display_values.values()],
                        }
                    )
        if _is_latest_status(
            role,
            message_id,
            latest_assistant_id,
            session,
            "awaiting_approval",
        ):
            if config_data:
                if st.button(
                    "Confirm configuration",
                    type="primary",
                    key=f"confirm-{message_id}",
                ):
                    _confirm_message(
                        client, actor_id, thread_id, message_id, config_data,
                    )
            else:
                st.caption(
                    "Waiting for Aryx's structured payload before this "
                    "can be confirmed — try again in a moment."
                )
        elif (
            _is_latest_status(
                role,
                message_id,
                latest_assistant_id,
                session,
                "post_approval",
            )
            and message.get("cpq_payload")
            and not has_workflow
        ):
            st.warning(
                "Configuration is confirmed, but no MSI workflow is "
                "recorded yet."
            )
            if st.button(
                "Create MSI quote",
                type="primary",
                key=f"create-msi-{message_id}",
            ):
                _confirm_message(
                    client, actor_id, thread_id, message_id, config_data or {},
                )


def _render_chat(
    client: SalesMcpClient,
    actor_id: str,
    messages: list[dict[str, Any]],
) -> None:
    """Render the transcript, relevant confirm action, and chat input."""
    thread_id = str(st.session_state["sales_thread_id"])
    latest_assistant_id = next(
        (
            str(message["id"])
            for message in reversed(messages)
            if message.get("role") == "assistant"
        ),
        "",
    )
    for message in messages:
        _render_message(
            client,
            actor_id,
            thread_id,
            message,
            latest_assistant_id,
        )

    prompt = st.chat_input("Describe the quote or answer Aryx…")
    if prompt:
        try:
            with st.spinner("Aryx is configuring…"):
                client.send(
                    actor_id,
                    thread_id,
                    str(uuid.uuid4()),
                    prompt,
                )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


def main() -> None:
    """Render the complete sales quote application."""
    st.title("Sales Quote Assistant")
    st.caption("Chat with Aryx to configure a product and create the MSI quote.")
    try:
        workspaces = _configured_workspaces()
        if not workspaces:
            raise RuntimeError(
                "No sales workspace configured — set ARYX_SALES_WORKSPACES "
                "(or ARYX_SALES_MCP_API_KEY for a single workspace)"
            )
        with st.sidebar:
            st.subheader("Workspace")
            selected_label = st.selectbox(
                "Workspace", list(workspaces.keys()), key="sales_workspace_label",
            )
        if st.session_state.get("_active_sales_workspace") != selected_label:
            # A leftover thread_id from the previous workspace's token scope
            # would just silently render empty (different workspace_id) —
            # clear it so switching workspaces starts a clean chat instead.
            st.session_state["_active_sales_workspace"] = selected_label
            st.session_state.pop("sales_thread_id", None)
        actor_id = resolve_actor_id(
            st.context.headers, st.session_state, st.query_params,
        )
        client = _mcp_client(workspaces[selected_label])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Application configuration error: {exc}")
        st.stop()

    chat_column, thread_column = st.columns([4, 1], gap="large")
    try:
        threads = client.list_threads(actor_id)
        if not st.session_state.get("sales_thread_id"):
            started = client.start(actor_id)
            st.session_state["sales_thread_id"] = started["thread_id"]
        with thread_column:
            st.subheader("Chats")
            if st.button("＋ New chat", use_container_width=True):
                started = client.start(actor_id)
                st.session_state["sales_thread_id"] = started["thread_id"]
                st.rerun()
            for thread in threads:
                label = str(thread.get("title") or "New chat")
                if st.button(
                    label,
                    key=f"thread-{thread['id']}",
                    use_container_width=True,
                    disabled=thread["id"]
                    == st.session_state.get("sales_thread_id"),
                ):
                    st.session_state["sales_thread_id"] = thread["id"]
                    st.rerun()
        with chat_column:
            messages = _load_messages(client, actor_id)
            if not messages:
                st.info(
                    "Start by describing the customer, product, and configuration."
                )
            _render_chat(client, actor_id, messages)
    except Exception as exc:  # noqa: BLE001
        with chat_column:
            st.error(str(exc))


if __name__ == "__main__":
    main()
