"""Ask panel — LLM-backed chat over the graph via the REST /ask endpoint.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`ask_panel_samples.py` (`_entity_ids_from`/`_samples_for`/`_sample_chips`)
and `ask_panel_render.py` (`_render_usage`/`_render_cpq_buttons`/
`_render_msg`), both re-imported here. Zero whitebox test patches exist
anywhere against `aryx.ui.ask_panel.*` (confirmed via grep; this module
has no importers besides Streamlit's own page loader), so the split was
purely mechanical. `render()` — wiring the whole page together — stays
here.
"""
from __future__ import annotations

import uuid

import streamlit as st

from aryx.ui import ask_export, ask_history_panel, toast as _toast, workspace_summary
from aryx.ui import api
from aryx.ui.ask_panel_render import _render_msg, _render_usage
from aryx.ui.ask_panel_samples import _entity_ids_from, _sample_chips

__all__ = ["render"]


def render() -> None:
    st.title("Ask the Graph")
    workspace_summary.render("Ask")

    if "chat" not in st.session_state:
        st.session_state.chat = []
        st.session_state.cpq_session_data = {}
        st.session_state.cpq_conversation_id = str(uuid.uuid4())

    if not st.session_state.chat:
        _sample_chips()

    for idx, msg in enumerate(st.session_state.chat):
        _render_msg(msg, idx)

    if st.session_state.chat:
        with st.expander("⬇️  Download this conversation", expanded=False):
            ask_export.download_buttons(st.session_state.chat, key_suffix="current")
    with st.expander("🗂  Past conversations (persisted)", expanded=False):
        ask_history_panel.render()

    queued = st.session_state.pop("queued_question", None)
    question = queued or st.chat_input("Ask anything about your graph…")
    if not question:
        return

    user_msg = {"role": "user", "text": question}
    st.session_state.chat.append(user_msg)
    _render_msg(user_msg)

    history = [{"role": m["role"], "text": m["text"]} for m in st.session_state.chat[:-1][-5:]]
    with st.chat_message("assistant"):
        with st.spinner("Thinking — reading the graph…"):
            try:
                resp = api.ask(question, history, session_data=st.session_state.cpq_session_data)
            except Exception as exc:
                resp = {"answer": f"Error reaching Ask API: {exc}", "tools_called": [], "usage": {}}
        st.session_state.cpq_session_data = resp.get("session_data") or {}
        st.markdown(resp.get("answer", "(no answer)"))
        tools = resp.get("tools_called", [])
        if tools:
            with st.expander(f"Graph calls ({len(tools)})"):
                for t in tools:
                    st.code(t, language="text")
        if resp.get("usage"):
            _render_usage(resp["usage"])

    st.session_state.chat.append({
        "role": "assistant",
        "text": resp.get("answer", "(no answer)"),
        "tools": tools,
        "entity_ids": _entity_ids_from(resp),
        "usage": resp.get("usage", {}),
        "json_button_flag": resp.get("json_button_flag", False),
        "json_response": resp.get("json_response"),
        "beautify_button_flag": resp.get("beautify_button_flag", False),
        "beautify": resp.get("beautify"),
        "api_share_button_flag": resp.get("api_share_button_flag", False),
    })
    _toast.notify(
        f"Ask answered ({resp.get('usage', {}).get('latency_ms', 0)} ms)",
        kind="info", stage="Ask", action="ask",
        target=question[:80], workspace_id=api.current_workspace(),
        audit_event=True,
    )
