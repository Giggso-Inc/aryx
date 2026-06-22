"""Ingest tab — REST / API source. Preview then ingest to graph."""
from __future__ import annotations

import json

import streamlit as st

from aryx.ui import api, ingest_client


def render(workspace_context: str = "") -> None:
    """REST API form: URL + auth + record path + entity config → ingest job."""
    if workspace_context.strip():
        st.markdown(
            f'<div class="aryx-ws-summary">📝 <b>Workspace context:</b> '
            f'<i>{workspace_context}</i></div>',
            unsafe_allow_html=True,
        )
    st.markdown("**REST API endpoint** — Aryx will fetch JSON and treat each "
                "object as one record.")
    url = st.text_input("URL",
                        placeholder="https://api.example.com/v1/customers")
    auth_kind = st.selectbox("Auth", ["None", "Bearer", "API-Key header"])
    auth_value = ""
    api_key_name = "X-API-Key"
    if auth_kind == "Bearer":
        auth_value = st.text_input("Bearer token", type="password")
    elif auth_kind == "API-Key header":
        api_key_name = st.text_input("Header name", value="X-API-Key")
        auth_value = st.text_input("API key", type="password")
    record_path = st.text_input(
        "Records JSON path (dotted; empty = top-level list)",
        placeholder="data.items",
    )
    col1, col2 = st.columns(2)
    page_param = col1.text_input("Pagination query param (optional)",
                                 placeholder="page_token")
    next_path = col2.text_input("Next-page JSON path (optional)",
                                placeholder="next_page")
    headers: dict[str, str] = {}
    if auth_kind == "Bearer" and auth_value:
        headers["Authorization"] = f"Bearer {auth_value}"
    elif auth_kind == "API-Key header" and auth_value:
        headers[api_key_name] = auth_value

    st.divider()

    if st.button("🔍 Preview fetch", type="secondary", disabled=not url.strip()):
        try:
            payload = {
                "workspace_id": api.current_workspace(),
                "url": url, "headers": headers,
                "record_path": record_path,
                "page_param": page_param, "next_page_path": next_path,
                "context": workspace_context,
            }
            resp = api._post("/ingest/rest/preview", payload, timeout=60)
            st.session_state["rest_preview"] = resp
            st.session_state["rest_url"] = url
            st.session_state["rest_headers"] = headers
            st.session_state["rest_record_path"] = record_path
            st.session_state["rest_page_param"] = page_param
            st.session_state["rest_next_path"] = next_path
        except Exception as exc:
            st.error(f"Fetch failed: {exc}")

    prev = st.session_state.get("rest_preview")
    if prev and st.session_state.get("rest_url") == url:
        st.success(f"Fetched {prev.get('count', 0)} record(s).")
        with st.expander("Sample records", expanded=False):
            st.json(prev.get("sample", [])[:5])

        st.markdown("**Configure entity type before ingesting:**")
        c1, c2 = st.columns(2)
        otype = c1.text_input(
            "Entity type (PascalCase)",
            value=prev.get("inferred_type", "Entity"),
            key="rest_otype",
        )
        match_keys_raw = c2.text_input(
            "Match key(s) — comma separated",
            value=prev.get("suggested_match_key", "id"),
            key="rest_mk",
        )
        max_pages = st.number_input("Max pages to fetch", min_value=1,
                                    max_value=1000, value=20, key="rest_maxpages")
        st.caption("Connect & ingest will run the full pipeline: "
                   "extract → resolve → project to graph.")
        if st.button("🚀 Ingest to graph", type="primary", disabled=not otype.strip()):
            try:
                keys = [k.strip() for k in match_keys_raw.split(",") if k.strip()]
                payload = {
                    "workspace_id": api.current_workspace(),
                    "url": st.session_state["rest_url"],
                    "headers": st.session_state["rest_headers"],
                    "record_path": st.session_state["rest_record_path"],
                    "page_param": st.session_state["rest_page_param"],
                    "next_page_path": st.session_state["rest_next_path"],
                    "max_pages": int(max_pages),
                    "ontology_type": otype.strip(),
                    "match_keys": keys or ["id"],
                    "context": workspace_context,
                }
                resp = api._post("/ingest/rest/ingest", payload, timeout=30)
                st.session_state["active_job"] = resp.get("job_id")
                st.session_state.pop("rest_preview", None)
                st.success(f"Ingest queued — entity type: **{resp.get('ontology_type')}**")
                st.rerun()
            except Exception as exc:
                st.error(f"Ingest failed: {exc}")

    with st.expander("Preview the request"):
        st.code(json.dumps({"url": url, "headers": headers,
                            "record_path": record_path}, indent=2),
                language="json")
