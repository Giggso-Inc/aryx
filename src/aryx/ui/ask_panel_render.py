"""Per-message rendering (usage line, CPQ action buttons, chat bubble) for
the Ask panel.

Split out of `ui/ask_panel.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import json

import streamlit as st

from aryx.ui import api, toast as _toast


def _render_usage(usage: dict) -> None:
    cols = st.columns(3)
    cols[0].caption(f"⏱ {usage.get('latency_ms', 0)} ms")
    cols[1].caption(f"🔢 {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} tok")
    cols[2].caption(f"🧠 {usage.get('answer_model', '?')}")


def _render_cpq_buttons(msg: dict, idx: int) -> None:
    """JSON / Beautify / Share action buttons — driven by flags the backend
    already computed from session state (no extra LLM call on click)."""
    if not (msg.get("json_button_flag") or msg.get("beautify_button_flag")
            or msg.get("api_share_button_flag")):
        return
    cols = st.columns(3)
    if msg.get("json_button_flag") and cols[0].button("📋 JSON", key=f"json_btn_{idx}"):
        st.session_state[f"show_json_{idx}"] = not st.session_state.get(f"show_json_{idx}", False)
    if msg.get("beautify_button_flag") and cols[1].button("✨ Beautify", key=f"beautify_btn_{idx}"):
        st.session_state[f"show_beautify_{idx}"] = not st.session_state.get(f"show_beautify_{idx}", False)
    if msg.get("api_share_button_flag") and cols[2].button("📤 Share", key=f"share_btn_{idx}"):
        st.session_state[f"show_share_{idx}"] = not st.session_state.get(f"show_share_{idx}", False)

    if st.session_state.get(f"show_json_{idx}"):
        st.code(json.dumps(msg.get("json_response") or {}, indent=2), language="json")
    if st.session_state.get(f"show_beautify_{idx}"):
        st.code(msg.get("beautify") or "", language="text")
    if st.session_state.get(f"show_share_{idx}"):
        with st.form(key=f"share_form_{idx}"):
            endpoint_url = st.text_input(
                "Endpoint URL", key=f"share_url_{idx}",
                placeholder="https://api.example.com/v1/customers")
            col_a, col_b = st.columns(2)
            auth_header_name = col_a.text_input(
                "Auth header name", value="Authorization", key=f"share_hname_{idx}")
            auth_header_value = col_b.text_input(
                "Auth header value", type="password", key=f"share_hval_{idx}")
            submitted = st.form_submit_button("Share")
        if submitted:
            if not endpoint_url.strip():
                st.error("Endpoint URL is required.")
            else:
                try:
                    api.share_config(
                        st.session_state.cpq_conversation_id, msg.get("json_response") or {},
                        endpoint_url=endpoint_url.strip(),
                        auth_header_name=auth_header_name.strip() or "Authorization",
                        auth_header_value=auth_header_value,
                    )
                    _toast.notify(
                        "Configuration shared", kind="success", stage="Ask", action="share_config",
                        target=st.session_state.cpq_conversation_id, workspace_id=api.current_workspace(),
                        audit_event=True,
                    )
                except Exception as exc:
                    st.error(f"Share failed: {exc}")


def _render_msg(msg: dict, idx: int = 0) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        if msg.get("tools"):
            with st.expander(f"Graph calls ({len(msg['tools'])})"):
                for t in msg["tools"]:
                    st.code(t, language="text")
        ids = msg.get("entity_ids") or []
        if ids and st.button(
            f"🔍 View {len(ids)} entit{'y' if len(ids) == 1 else 'ies'} in Graph",
            key=f"viewgraph_{idx}", type="secondary",
        ):
            st.session_state["focus_ids"] = ids
            st.session_state["nav_target"] = "🕸️  Graph"
            st.rerun()
        _render_cpq_buttons(msg, idx)
        if msg.get("usage"):
            _render_usage(msg["usage"])
